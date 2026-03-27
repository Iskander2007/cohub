from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from rest_framework import status
from rest_framework.test import APITestCase
from django.test import RequestFactory, override_settings

from .models import Room, RoomMember, Expense, ExpenseShare, DebtSettlement, Task
from .views import (
    clear_failed_login_attempts,
    is_login_rate_limited,
    register_failed_login_attempt,
    validate_avatar_upload,
)


class CohubApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.owner = User.objects.create_user(username='owner@example.com', password='password123')
        self.member = User.objects.create_user(username='member@example.com', password='password123')
        self.outsider = User.objects.create_user(username='outsider@example.com', password='password123')

        self.room = Room.objects.create(
            name='Room A',
            code='ABC123',
            owner=self.owner,
            description='Test room',
        )
        RoomMember.objects.create(room=self.room, user=self.owner, is_admin=True)
        RoomMember.objects.create(room=self.room, user=self.member, is_admin=False)

    def tearDown(self):
        cache.clear()

    def test_join_room_is_case_insensitive(self):
        self.client.force_authenticate(user=self.outsider)

        response = self.client.post('/api/rooms/join_room/', {'code': 'abc123'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(RoomMember.objects.filter(room=self.room, user=self.outsider).exists())

    def test_task_creation_requires_assignee_in_same_room(self):
        self.client.force_authenticate(user=self.owner)
        payload = {
            'room': str(self.room.id),
            'title': 'Buy groceries',
            'description': 'Milk and bread',
            'assigned_to_id': self.outsider.id,
            'priority': 'medium',
            'status': 'pending',
        }

        response = self.client.post('/api/tasks/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('assigned_to_id', response.data)

    def test_expense_creation_requires_payer_in_same_room(self):
        self.client.force_authenticate(user=self.owner)
        payload = {
            'room': str(self.room.id),
            'description': 'Internet',
            'amount': '2500.00',
            'paid_by_id': self.outsider.id,
            'category': 'utilities',
        }

        response = self.client.post('/api/expenses/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('paid_by_id', response.data)

    def test_expense_creation_defaults_payer_to_current_user(self):
        self.client.force_authenticate(user=self.member)
        payload = {
            'room': str(self.room.id),
            'description': 'Water',
            'amount': '1200.00',
            'category': 'utilities',
        }

        response = self.client.post('/api/expenses/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['paid_by']['id'], self.member.id)

    def test_chat_message_cannot_be_blank(self):
        self.client.force_authenticate(user=self.member)
        payload = {
            'room': str(self.room.id),
            'text': '   ',
        }

        response = self.client.post('/api/chat-messages/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('text', response.data)

    def test_expense_share_visibility_limited_to_user_rooms(self):
        # Create another room where only outsider participates
        outsider_room = Room.objects.create(
            name='Room B',
            code='XYZ789',
            owner=self.outsider,
            description='Hidden room',
        )
        RoomMember.objects.create(room=outsider_room, user=self.outsider, is_admin=True)

        visible_expense = Expense.objects.create(
            room=self.room,
            description='Visible expense',
            amount='1000.00',
            paid_by=self.owner,
            category='food',
        )
        hidden_expense = Expense.objects.create(
            room=outsider_room,
            description='Hidden expense',
            amount='500.00',
            paid_by=self.outsider,
            category='misc',
        )

        visible_share = ExpenseShare.objects.create(expense=visible_expense, user=self.member, amount='500.00')
        ExpenseShare.objects.create(expense=hidden_expense, user=self.outsider, amount='500.00')

        self.client.force_authenticate(user=self.member)
        response = self.client.get('/api/expense-shares/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.data.get('results', response.data)
        returned_ids = {item['id'] for item in payload}
        self.assertIn(str(visible_share.id), returned_ids)
        self.assertEqual(len(returned_ids), 1)

    def test_settle_between_closes_room_debt_in_statistics(self):
        expense = Expense.objects.create(
            room=self.room,
            description='Groceries',
            amount='3000.00',
            paid_by=self.owner,
            category='food',
        )
        ExpenseShare.objects.create(expense=expense, user=self.member, amount='1000.00', is_settled=False)

        self.client.force_authenticate(user=self.owner)
        stats_before = self.client.get(f'/api/rooms/{self.room.id}/statistics/')
        self.assertEqual(stats_before.status_code, status.HTTP_200_OK)
        self.assertEqual(len(stats_before.data['debts']), 1)

        settle_response = self.client.post('/api/expense-shares/settle_between/', {
            'room': str(self.room.id),
            'from_user_id': self.member.id,
            'to_user_id': self.owner.id,
        }, format='json')
        self.assertEqual(settle_response.status_code, status.HTTP_200_OK)
        self.assertEqual(settle_response.data['settled_count'], 1)
        self.assertEqual(settle_response.data['settled_amount'], 1000.0)

        settlement = DebtSettlement.objects.get(room=self.room)
        self.assertEqual(settlement.from_user_id, self.member.id)
        self.assertEqual(settlement.to_user_id, self.owner.id)
        self.assertEqual(float(settlement.amount), 1000.0)

        stats_after = self.client.get(f'/api/rooms/{self.room.id}/statistics/')
        self.assertEqual(stats_after.status_code, status.HTTP_200_OK)
        self.assertEqual(stats_after.data['debts'], [])
        self.assertEqual(len(stats_after.data['recent_settlements']), 1)
        self.assertEqual(stats_after.data['recent_settlements'][0]['amount'], 1000.0)

    def test_room_assistant_returns_recommendations(self):
        Expense.objects.create(
            room=self.room,
            description='Groceries',
            amount='6000.00',
            paid_by=self.owner,
            category='Еда',
        )
        Expense.objects.create(
            room=self.room,
            description='Internet',
            amount='1500.00',
            paid_by=self.member,
            category='Интернет',
        )
        Task.objects.create(
            room=self.room,
            title='Clean kitchen',
            status='pending',
            priority='medium',
            created_by=self.owner,
        )

        self.client.force_authenticate(user=self.owner)
        response = self.client.get(f'/api/rooms/{self.room.id}/assistant/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('expense_insights', response.data)
        self.assertIn('shopping_list', response.data)
        self.assertIn('task_suggestions', response.data)
        self.assertIn('personal_suggestions', response.data)
        self.assertEqual(response.data['metrics']['period_days'], 30)
        self.assertTrue(len(response.data['expense_insights']) >= 1)
        self.assertTrue(len(response.data['shopping_list']) >= 1)

    def test_assistant_apply_actions_create_and_assign_tasks(self):
        Task.objects.create(
            room=self.room,
            title='Unassigned task 1',
            status='pending',
            priority='medium',
            created_by=self.owner,
        )
        Task.objects.create(
            room=self.room,
            title='Unassigned task 2',
            status='pending',
            priority='medium',
            created_by=self.owner,
        )

        self.client.force_authenticate(user=self.owner)

        apply_shopping = self.client.post(
            f'/api/rooms/{self.room.id}/assistant_apply_shopping/',
            {'shopping_list': ['Молоко', 'Рис']},
            format='json',
        )
        self.assertEqual(apply_shopping.status_code, status.HTTP_200_OK)
        self.assertEqual(apply_shopping.data['created_count'], 2)

        apply_tasks = self.client.post(f'/api/rooms/{self.room.id}/assistant_apply_tasks/', {}, format='json')
        self.assertEqual(apply_tasks.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(apply_tasks.data['updated_count'], 2)

        self.assertTrue(
            Task.objects.filter(room=self.room, title='Купить: Молоко', assigned_to=self.owner).exists()
        )
        self.assertFalse(Task.objects.filter(room=self.room, title='Unassigned task 1', assigned_to__isnull=True).exists())

    def test_assistant_apply_personal_assigns_task_to_target_member(self):
        Task.objects.create(
            room=self.room,
            title='Owner overloaded 1',
            status='pending',
            priority='medium',
            created_by=self.owner,
            assigned_to=self.owner,
        )
        Task.objects.create(
            room=self.room,
            title='Owner overloaded 2',
            status='pending',
            priority='medium',
            created_by=self.owner,
            assigned_to=self.owner,
        )

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            f'/api/rooms/{self.room.id}/assistant_apply_personal/',
            {'user_id': self.member.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['updated_count'], 1)
        self.assertEqual(response.data['target_user_id'], self.member.id)
        self.assertTrue(Task.objects.filter(room=self.room, assigned_to=self.member).exists())

    def test_api_throttling_blocks_burst_requests(self):
        self.client.login(username='owner@example.com', password='password123')
        request_limit = int(settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['user'].split('/')[0])

        for _ in range(request_limit):
            response = self.client.get('/api/rooms/')
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        throttled = self.client.get('/api/rooms/')
        self.assertEqual(throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @override_settings(LOGIN_RATE_LIMIT=2, LOGIN_RATE_LIMIT_WINDOW=60)
    def test_failed_login_attempts_are_rate_limited(self):
        request = self.factory.post('/account/login/')
        request.META['REMOTE_ADDR'] = '127.0.0.1'

        self.assertFalse(is_login_rate_limited(request, 'owner@example.com'))

        register_failed_login_attempt(request, 'owner@example.com')
        self.assertFalse(is_login_rate_limited(request, 'owner@example.com'))

        register_failed_login_attempt(request, 'owner@example.com')
        self.assertTrue(is_login_rate_limited(request, 'owner@example.com'))

        clear_failed_login_attempts(request, 'owner@example.com')
        self.assertFalse(is_login_rate_limited(request, 'owner@example.com'))

    @override_settings(AVATAR_MAX_UPLOAD_SIZE=32)
    def test_avatar_validator_rejects_oversized_files(self):
        avatar = SimpleUploadedFile('avatar.png', b'0' * 64, content_type='image/png')

        with self.assertRaises(ValidationError):
            validate_avatar_upload(avatar)

    def test_backup_command_creates_json_backup(self):
        with TemporaryDirectory() as temp_dir:
            call_command('backup_data', '--output-dir', temp_dir)

            backup_files = list(Path(temp_dir).glob('cohub-backup-*.json'))
            self.assertEqual(len(backup_files), 1)

            backup_content = backup_files[0].read_text(encoding='utf-8')
            self.assertIn('"model": "auth.user"', backup_content)
            self.assertIn('"model": "cohub_app.room"', backup_content)
