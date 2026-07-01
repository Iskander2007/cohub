from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from django.test import RequestFactory, override_settings

from .models import Room, RoomMember, Expense, ExpenseShare, DebtSettlement, Loan, LoanPayment, Task, ChatMessage, TaskReassignmentRequest
from .views import (
    clear_failed_login_attempts,
    is_login_rate_limited,
    register_failed_login_attempt,
    validate_avatar_upload,
)


# Тесты входа/регистрации проверяют встроенную арифметическую CAPTCHA, поэтому
# принудительно отключаем Google reCAPTCHA — иначе ключи из локального .env
# разработчика «протекают» в тесты и ломают их (код требует токен Google).
@override_settings(RECAPTCHA_SITE_KEY='', RECAPTCHA_SECRET_KEY='')
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

    def test_shared_utility_expense_can_be_created_without_single_payer(self):
        self.client.force_authenticate(user=self.owner)
        payload = {
            'room': str(self.room.id),
            'description': 'Коммуналка за месяц',
            'amount': '10000.00',
            'category': 'Коммуналка',
            'shared_with_room': True,
        }

        response = self.client.post('/api/expenses/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data['paid_by'])
        self.assertTrue(response.data['is_shared'])

        expense = Expense.objects.get(id=response.data['id'])
        shares = ExpenseShare.objects.filter(expense=expense).order_by('user_id')
        self.assertEqual(shares.count(), 2)
        self.assertTrue(all(str(share.amount) == '5000.00' for share in shares))

    def test_expense_creation_with_mark_as_paid_sets_all_shares_settled(self):
        self.client.force_authenticate(user=self.member)
        payload = {
            'room': str(self.room.id),
            'description': 'АВПВЫВЫПИВЫМАВЫ',
            'amount': '3000.00',
            'category': 'Коммуналка',
            'shared_with_room': True,
            'mark_as_paid': True,
        }

        response = self.client.post('/api/expenses/', payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        expense = Expense.objects.get(id=response.data['id'])
        shares = ExpenseShare.objects.filter(expense=expense)
        self.assertTrue(shares.exists())
        self.assertTrue(all(share.is_settled for share in shares))

    def test_shared_expense_shares_sum_to_total_with_remainder(self):
        # Сумма, не делящаяся нацело: доли всё равно должны давать ровно total.
        self.client.force_authenticate(user=self.owner)
        response = self.client.post('/api/expenses/', {
            'room': str(self.room.id),
            'description': 'Неделимый расход',
            'amount': '10.01',
            'category': 'misc',
            'shared_with_room': True,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        expense = Expense.objects.get(id=response.data['id'])
        shares = list(ExpenseShare.objects.filter(expense=expense))
        self.assertEqual(len(shares), 2)
        self.assertEqual(float(sum(share.amount for share in shares)), 10.01)

    def test_task_status_cannot_be_completed_via_direct_patch(self):
        # Прямой PATCH status='completed' не должен закрывать задачу в обход
        # проверки прав (status — read-only, завершение только через action).
        task = Task.objects.create(
            room=self.room, title='Помыть пол', status='pending', priority='medium',
            created_by=self.owner, assigned_to=self.member,
        )

        self.client.force_authenticate(user=self.member)
        self.client.patch(f'/api/tasks/{task.id}/', {'status': 'completed'}, format='json')

        task.refresh_from_db()
        self.assertEqual(task.status, 'pending')

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

    def test_statistics_includes_payment_insights(self):
        loan = Loan.objects.create(
            room=self.room,
            lender=self.owner,
            borrower=self.member,
            amount_total='800.00',
            due_date=(timezone.localdate() + timezone.timedelta(days=7)),
            created_by=self.owner,
        )
        LoanPayment.objects.create(
            loan=loan,
            amount='300.00',
            paid_by=self.member,
            note='Частичная оплата',
        )
        DebtSettlement.objects.create(
            room=self.room,
            from_user=self.member,
            to_user=self.owner,
            amount='150.00',
            settled_by=self.member,
        )

        self.client.force_authenticate(user=self.owner)
        stats_response = self.client.get(f'/api/rooms/{self.room.id}/statistics/')

        self.assertEqual(stats_response.status_code, status.HTTP_200_OK)
        self.assertIn('payment_insights', stats_response.data)
        insights = stats_response.data['payment_insights']
        self.assertEqual(insights['settlement_count'], 2)
        self.assertEqual(insights['loan_payment_total'], 300.0)
        self.assertEqual(insights['debt_settlement_total'], 150.0)
        self.assertEqual(insights['total_paid_amount'], 450.0)
        self.assertEqual(len(insights['recent_payments']), 2)

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

    def test_assigned_user_can_create_task_reassignment_request(self):
        task = Task.objects.create(
            room=self.room,
            title='Выкинуть мусор',
            status='pending',
            priority='medium',
            created_by=self.owner,
            assigned_to=self.owner,
        )

        self.client.force_authenticate(user=self.owner)
        response = self.client.post('/api/task-reassignment-requests/', {
            'task_id': str(task.id),
            'requested_to_id': self.member.id,
            'reason': 'illness',
            'custom_message': 'Сегодня не успеваю, можешь подменить?',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], 'pending')
        self.assertEqual(response.data['reason'], 'illness')
        self.assertEqual(response.data['requested_to']['id'], self.member.id)

    def test_recipient_can_accept_task_reassignment_request_and_receives_chat_notice(self):
        task = Task.objects.create(
            room=self.room,
            title='Купить продукты',
            status='pending',
            priority='high',
            created_by=self.owner,
            assigned_to=self.owner,
        )

        self.client.force_authenticate(user=self.owner)
        create_response = self.client.post('/api/task-reassignment-requests/', {
            'task_id': str(task.id),
            'requested_to_id': self.member.id,
            'reason': 'exam',
            'custom_message': 'У меня подготовка к экзамену',
        }, format='json')

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        request_id = create_response.data['id']

        self.client.force_authenticate(user=self.member)
        accept_response = self.client.post(
            f'/api/task-reassignment-requests/{request_id}/accept/',
            {'response_note': 'Ок, я возьму это на себя'},
            format='json',
        )

        self.assertEqual(accept_response.status_code, status.HTTP_200_OK)
        self.assertEqual(accept_response.data['status'], 'accepted')

        task.refresh_from_db()
        self.assertEqual(task.assigned_to, self.member)
        self.assertTrue(ChatMessage.objects.filter(room=self.room, text__icontains='принял').exists())

    def test_requester_can_cancel_pending_task_reassignment_request(self):
        task = Task.objects.create(
            room=self.room,
            title='Помыть посуду',
            status='pending',
            priority='medium',
            created_by=self.owner,
            assigned_to=self.owner,
        )

        self.client.force_authenticate(user=self.owner)
        create_response = self.client.post('/api/task-reassignment-requests/', {
            'task_id': str(task.id),
            'requested_to_id': self.member.id,
            'reason': 'work',
            'custom_message': 'Срочно занят по работе',
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        request_id = create_response.data['id']
        cancel_response = self.client.post(
            f'/api/task-reassignment-requests/{request_id}/cancel/',
            {'response_note': 'Уже успеваю сам(а)'},
            format='json',
        )

        self.assertEqual(cancel_response.status_code, status.HTTP_200_OK)
        self.assertEqual(cancel_response.data['status'], 'cancelled')
        self.assertTrue(ChatMessage.objects.filter(room=self.room, text__icontains='отмен').exists())

    def test_clear_task_reassignment_history_removes_only_closed_requests(self):
        completed_request = Task.objects.create(
            room=self.room,
            title='Протереть пыль',
            status='pending',
            priority='medium',
            created_by=self.owner,
            assigned_to=self.owner,
        )
        active_request = Task.objects.create(
            room=self.room,
            title='Сходить в магазин',
            status='pending',
            priority='medium',
            created_by=self.owner,
            assigned_to=self.owner,
        )

        self.client.force_authenticate(user=self.owner)
        closed_response = self.client.post('/api/task-reassignment-requests/', {
            'task_id': str(completed_request.id),
            'requested_to_id': self.member.id,
            'reason': 'family',
            'custom_message': 'Нужно отъехать по семейным делам',
        }, format='json')
        pending_response = self.client.post('/api/task-reassignment-requests/', {
            'task_id': str(active_request.id),
            'requested_to_id': self.member.id,
            'reason': 'illness',
            'custom_message': 'Плохо себя чувствую',
        }, format='json')
        self.assertEqual(closed_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(pending_response.status_code, status.HTTP_201_CREATED)

        cancel_response = self.client.post(
            f"/api/task-reassignment-requests/{closed_response.data['id']}/cancel/",
            {'response_note': 'Уже неактуально'},
            format='json',
        )
        self.assertEqual(cancel_response.status_code, status.HTTP_200_OK)

        clear_response = self.client.post('/api/task-reassignment-requests/clear_history/', {
            'room': str(self.room.id),
        }, format='json')

        self.assertEqual(clear_response.status_code, status.HTTP_200_OK)
        self.assertEqual(clear_response.data['deleted_count'], 1)
        self.assertFalse(TaskReassignmentRequest.objects.filter(id=closed_response.data['id']).exists())
        self.assertTrue(TaskReassignmentRequest.objects.filter(id=pending_response.data['id'], status='pending').exists())

    def test_non_creator_cannot_complete_task_without_transfer(self):
        task = Task.objects.create(
            room=self.room,
            title='Пропылесосить комнату',
            status='pending',
            priority='medium',
            created_by=self.owner,
            assigned_to=self.member,
        )

        self.client.force_authenticate(user=self.member)
        response = self.client.post(f'/api/tasks/{task.id}/complete/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        task.refresh_from_db()
        self.assertEqual(task.status, 'pending')

    def test_transfer_recipient_can_complete_task_after_acceptance(self):
        task = Task.objects.create(
            room=self.room,
            title='Помыть окна',
            status='pending',
            priority='medium',
            created_by=self.owner,
            assigned_to=self.owner,
        )

        self.client.force_authenticate(user=self.owner)
        create_response = self.client.post('/api/task-reassignment-requests/', {
            'task_id': str(task.id),
            'requested_to_id': self.member.id,
            'reason': 'work',
            'custom_message': 'Не успеваю сегодня',
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        self.client.force_authenticate(user=self.member)
        accept_response = self.client.post(
            f"/api/task-reassignment-requests/{create_response.data['id']}/accept/",
            {'response_note': 'Хорошо, сделаю'},
            format='json',
        )
        self.assertEqual(accept_response.status_code, status.HTTP_200_OK)

        complete_response = self.client.post(f'/api/tasks/{task.id}/complete/', {}, format='json')
        self.assertEqual(complete_response.status_code, status.HTTP_200_OK)

        task.refresh_from_db()
        self.assertEqual(task.status, 'completed')
        self.assertEqual(task.assigned_to, self.member)

    def test_creator_cannot_complete_task_after_transfer_is_accepted(self):
        task = Task.objects.create(
            room=self.room,
            title='Разобрать шкаф',
            status='pending',
            priority='medium',
            created_by=self.owner,
            assigned_to=self.owner,
        )

        self.client.force_authenticate(user=self.owner)
        create_response = self.client.post('/api/task-reassignment-requests/', {
            'task_id': str(task.id),
            'requested_to_id': self.member.id,
            'reason': 'trip',
            'custom_message': 'Меня не будет дома',
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        self.client.force_authenticate(user=self.member)
        accept_response = self.client.post(
            f"/api/task-reassignment-requests/{create_response.data['id']}/accept/",
            {'response_note': 'Приму задачу'},
            format='json',
        )
        self.assertEqual(accept_response.status_code, status.HTTP_200_OK)

        self.client.force_authenticate(user=self.owner)
        complete_response = self.client.post(f'/api/tasks/{task.id}/complete/', {}, format='json')

        self.assertEqual(complete_response.status_code, status.HTTP_403_FORBIDDEN)
        task.refresh_from_db()
        self.assertEqual(task.status, 'pending')
        self.assertEqual(task.assigned_to, self.member)

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

    @override_settings(LOGIN_RATE_LIMIT=2, LOGIN_RATE_LIMIT_WINDOW=60)
    def test_login_view_returns_429_after_too_many_failed_attempts(self):
        payload = {
            'email': 'owner@example.com',
            'password': 'wrong-password',
        }

        with patch(
            'cohub_app.views.render',
            side_effect=lambda request, template_name, context=None, status=200: JsonResponse(context or {}, status=status),
        ):
            first_response = self.client.post('/account/login/', payload, REMOTE_ADDR='10.10.10.10')
            second_response = self.client.post('/account/login/', payload, REMOTE_ADDR='10.10.10.10')
            throttled_response = self.client.post('/account/login/', payload, REMOTE_ADDR='10.10.10.10')

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(throttled_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn('Слишком много неудачных попыток входа', throttled_response.json()['error'])

    def test_login_view_redirects_to_dashboard_on_success(self):
        # GET генерирует CAPTCHA и кладёт правильный ответ в сессию.
        self.client.get('/account/login/')
        captcha_answer = self.client.session['captcha_answer']

        response = self.client.post('/account/login/', {
            'email': 'owner@example.com',
            'password': 'password123',
            'captcha': captcha_answer,
        })

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response['Location'], '/dashboard/')

    def test_dashboard_page_includes_insights_preview_context(self):
        Task.objects.create(
            room=self.room,
            title='Take out trash',
            status='pending',
            priority='high',
            created_by=self.owner,
            assigned_to=self.owner,
        )
        Expense.objects.create(
            room=self.room,
            description='Groceries',
            amount='4500.00',
            paid_by=self.owner,
            category='Еда',
        )

        self.client.login(username='owner@example.com', password='password123')
        with patch(
            'cohub_app.views.render',
            side_effect=lambda request, template_name, context=None, status=200: JsonResponse({
                'insights_preview': (context or {}).get('insights_preview', {}),
                'show_insights_first': (context or {}).get('show_insights_first', False),
            }, status=status),
        ):
            response = self.client.get(f'/dashboard/{self.room.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload['show_insights_first'])
        self.assertIn('headline_metrics', payload['insights_preview'])
        self.assertIn('reminders', payload['insights_preview'])

    def test_dashboard_page_shows_monthly_budget_edit_button(self):
        self.client.login(username='owner@example.com', password='password123')

        with patch(
            'cohub_app.views.render',
            side_effect=lambda request, template_name, context=None, status=200: JsonResponse({
                'show_budget_editor': (context or {}).get('show_budget_editor', False),
                'budget_button_label': (context or {}).get('budget_button_label', ''),
            }, status=status),
        ):
            response = self.client.get(f'/dashboard/{self.room.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload['show_budget_editor'])
        self.assertEqual(payload['budget_button_label'], 'Изменить сумму')

    def test_register_view_rejects_weak_password_and_keeps_user_uncreated(self):
        payload = {
            'full_name': 'Weak Password',
            'email': 'weak@example.com',
            'password': '123',
            'password_confirm': '123',
            'terms': 'on',
        }

        with patch(
            'cohub_app.views.render',
            side_effect=lambda request, template_name, context=None, status=200: JsonResponse(context or {}, status=status),
        ):
            response = self.client.post('/register/', payload)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(User.objects.filter(username='weak@example.com').exists())
        self.assertTrue(response.json()['errors'])

    def test_protected_profile_redirects_to_project_login_page(self):
        response = self.client.get('/account/')

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response['Location'], '/account/login/?next=/account/')

    def test_api_responses_include_security_headers(self):
        response = self.client.get('/api/rooms/')

        self.assertIn(response.status_code, {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN})
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_room_insights_page_shows_achievements_mood_reminders_and_charts(self):
        Task.objects.create(
            room=self.room,
            title='Wash dishes',
            status='completed',
            priority='medium',
            created_by=self.owner,
            assigned_to=self.member,
        )
        Task.objects.create(
            room=self.room,
            title='Take out trash',
            status='pending',
            priority='high',
            created_by=self.owner,
            assigned_to=self.owner,
        )
        Expense.objects.create(
            room=self.room,
            description='Groceries',
            amount='4500.00',
            paid_by=self.owner,
            category='Еда',
        )

        self.client.login(username='owner@example.com', password='password123')
        with patch(
            'cohub_app.views.render',
            side_effect=lambda request, template_name, context=None, status=200: JsonResponse({
                'achievements': (context or {}).get('achievements', []),
                'reminders': (context or {}).get('reminders', []),
                'member_chart': (context or {}).get('member_chart', []),
                'expense_chart': (context or {}).get('expense_chart', []),
            }, status=status),
        ):
            response = self.client.get(f'/dashboard/{self.room.id}/insights/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertIn('achievements', payload)
        self.assertIn('reminders', payload)
        self.assertIn('member_chart', payload)
        self.assertIn('expense_chart', payload)

    def test_member_mood_update_is_visible_to_other_roommates(self):
        self.client.force_authenticate(user=self.member)
        update_response = self.client.post(
            f'/api/rooms/{self.room.id}/update_my_mood/',
            {
                'mood_key': 'tired',
                'mood_note': 'Сегодня лучше без шума вечером',
            },
            format='json',
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data['mood']['key'], 'tired')

        self.client.login(username='owner@example.com', password='password123')
        with patch(
            'cohub_app.views.render',
            side_effect=lambda request, template_name, context=None, status=200: JsonResponse({
                'participant_moods': (context or {}).get('participant_moods', []),
                'mood_overview': (context or {}).get('mood_overview', {}),
            }, status=status),
        ):
            response = self.client.get(f'/dashboard/{self.room.id}/insights/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        member_entry = next(item for item in payload['participant_moods'] if item['user_id'] == self.member.id)
        self.assertEqual(member_entry['mood_key'], 'tired')
        self.assertEqual(member_entry['note'], 'Сегодня лучше без шума вечером')
        self.assertIn('участ', payload['mood_overview']['label'].lower())

    def test_manual_loan_supports_partial_repayment(self):
        self.client.force_authenticate(user=self.owner)
        due_date = (timezone.localdate() + timezone.timedelta(days=7)).isoformat()

        create_response = self.client.post('/api/loans/', {
            'room': str(self.room.id),
            'borrower_id': self.member.id,
            'amount_total': '5000.00',
            'due_date': due_date,
            'note': 'На интернет',
        }, format='json')

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(float(create_response.data['remaining_amount']), 5000.0)
        self.assertEqual(create_response.data['status'], 'active')

        payment_response = self.client.post('/api/loan-payments/', {
            'loan_id': create_response.data['id'],
            'amount': '1500.00',
            'note': 'Частичный возврат',
        }, format='json')

        self.assertEqual(payment_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(float(payment_response.data['loan_remaining_amount']), 3500.0)

        loans_response = self.client.get(f'/api/loans/?room={self.room.id}')
        self.assertEqual(loans_response.status_code, status.HTTP_200_OK)
        payload = loans_response.data.get('results', loans_response.data)
        self.assertEqual(float(payload[0]['remaining_amount']), 3500.0)
        self.assertEqual(payload[0]['status'], 'partially_paid')

    def test_overdue_manual_loan_appears_in_room_notifications(self):
        self.client.force_authenticate(user=self.owner)
        due_date = (timezone.localdate() - timezone.timedelta(days=3)).isoformat()

        create_response = self.client.post('/api/loans/', {
            'room': str(self.room.id),
            'borrower_id': self.member.id,
            'amount_total': '2500.00',
            'due_date': due_date,
            'note': 'На продукты',
        }, format='json')
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        stats_response = self.client.get(f'/api/rooms/{self.room.id}/statistics/')

        self.assertEqual(stats_response.status_code, status.HTTP_200_OK)
        self.assertTrue(stats_response.data['loan_notifications'])
        self.assertEqual(stats_response.data['manual_loans'][0]['status'], 'overdue')

    def test_clear_debt_history_removes_history_but_keeps_active_loans(self):
        self.client.force_authenticate(user=self.owner)

        due_date = (timezone.localdate() + timezone.timedelta(days=5)).isoformat()
        loan_response = self.client.post('/api/loans/', {
            'room': str(self.room.id),
            'borrower_id': self.member.id,
            'amount_total': '5000.00',
            'due_date': due_date,
            'note': 'На аренду',
        }, format='json')
        self.assertEqual(loan_response.status_code, status.HTTP_201_CREATED)

        payment_response = self.client.post('/api/loan-payments/', {
            'loan_id': loan_response.data['id'],
            'amount': '1000.00',
            'note': 'Часть возврата',
        }, format='json')
        self.assertEqual(payment_response.status_code, status.HTTP_201_CREATED)

        expense = Expense.objects.create(
            room=self.room,
            description='Wi-Fi',
            amount='3000.00',
            paid_by=self.owner,
            category='internet',
        )
        ExpenseShare.objects.create(expense=expense, user=self.member, amount='1500.00', is_settled=False)
        settle_response = self.client.post('/api/expense-shares/settle_between/', {
            'room': str(self.room.id),
            'from_user_id': self.member.id,
            'to_user_id': self.owner.id,
        }, format='json')
        self.assertEqual(settle_response.status_code, status.HTTP_200_OK)

        clear_response = self.client.post(f'/api/rooms/{self.room.id}/clear_debt_history/', {}, format='json')

        self.assertEqual(clear_response.status_code, status.HTTP_200_OK)
        self.assertEqual(clear_response.data['deleted_payments'], 1)
        self.assertEqual(clear_response.data['deleted_settlements'], 1)

        stats_response = self.client.get(f'/api/rooms/{self.room.id}/statistics/')
        self.assertEqual(stats_response.status_code, status.HTTP_200_OK)
        self.assertEqual(stats_response.data['recent_settlements'], [])
        self.assertEqual(len(stats_response.data['manual_loans']), 1)
        self.assertEqual(float(stats_response.data['manual_loans'][0]['remaining_amount']), 4000.0)

    def test_room_member_can_clear_debt_history(self):
        self.client.force_authenticate(user=self.owner)
        due_date = (timezone.localdate() + timezone.timedelta(days=3)).isoformat()
        loan_response = self.client.post('/api/loans/', {
            'room': str(self.room.id),
            'borrower_id': self.member.id,
            'amount_total': '2000.00',
            'due_date': due_date,
            'note': 'На ужин',
        }, format='json')
        self.assertEqual(loan_response.status_code, status.HTTP_201_CREATED)

        payment_response = self.client.post('/api/loan-payments/', {
            'loan_id': loan_response.data['id'],
            'amount': '500.00',
            'note': 'Возврат части',
        }, format='json')
        self.assertEqual(payment_response.status_code, status.HTTP_201_CREATED)

        self.client.force_authenticate(user=self.member)
        clear_response = self.client.post(f'/api/rooms/{self.room.id}/clear_debt_history/', {}, format='json')

        self.assertEqual(clear_response.status_code, status.HTTP_200_OK)
        self.assertEqual(clear_response.data['deleted_payments'], 1)

    def test_backup_command_creates_json_backup(self):
        with TemporaryDirectory() as temp_dir:
            call_command('backup_data', '--output-dir', temp_dir)

            backup_files = list(Path(temp_dir).glob('cohub-backup-*.json'))
            self.assertEqual(len(backup_files), 1)

            backup_content = backup_files[0].read_text(encoding='utf-8')
            self.assertIn('"model": "auth.user"', backup_content)
            self.assertIn('"model": "cohub_app.room"', backup_content)


@override_settings(RECAPTCHA_SITE_KEY='', RECAPTCHA_SECRET_KEY='')
class SecurityFeaturesTests(APITestCase):
    """Тесты добавленных фич безопасности: CAPTCHA, RBAC, open redirect, заголовки."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='user@example.com', password='password123')
        self.admin = User.objects.create_user(
            username='admin@example.com', password='password123', is_staff=True,
        )
        self.room = Room.objects.create(name='Sec Room', code='SEC123', owner=self.user)
        RoomMember.objects.create(room=self.room, user=self.user, is_admin=True)

    def tearDown(self):
        cache.clear()

    # --- CAPTCHA (A07) ---
    def test_login_rejected_with_wrong_captcha(self):
        self.client.get('/account/login/')  # генерируем CAPTCHA в сессии
        response = self.client.post('/account/login/', {
            'email': 'user@example.com',
            'password': 'password123',
            'captcha': '-999',  # заведомо неверный ответ
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)  # форма с ошибкой, не редирект
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_succeeds_with_correct_captcha(self):
        self.client.get('/account/login/')
        answer = self.client.session['captcha_answer']
        response = self.client.post('/account/login/', {
            'email': 'user@example.com',
            'password': 'password123',
            'captcha': answer,
        })
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)

    # --- A01: open redirect ---
    def test_login_ignores_external_next_url(self):
        self.client.get('/account/login/')
        answer = self.client.session['captcha_answer']
        response = self.client.post('/account/login/', {
            'email': 'user@example.com',
            'password': 'password123',
            'captcha': answer,
            'next': 'https://evil.example.com/phish',
        })
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response['Location'], '/dashboard/')  # внешний адрес отброшен

    # --- RBAC ---
    def test_global_metrics_forbidden_for_regular_user(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/teacher-metrics/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_global_metrics_allowed_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get('/api/teacher-metrics/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_role_field_grants_admin_access(self):
        # Роль через профиль (без is_staff) тоже даёт доступ администратора.
        self.user.profile.role = 'admin'
        self.user.profile.save()
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/teacher-metrics/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_owner_member_cannot_delete_room(self):
        other = User.objects.create_user(username='other@example.com', password='password123')
        RoomMember.objects.create(room=self.room, user=other, is_admin=False)
        self.client.force_authenticate(user=other)
        response = self.client.delete(f'/api/rooms/{self.room.id}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Room.objects.filter(id=self.room.id).exists())

    # --- Security headers (A05) ---
    def test_security_headers_present(self):
        response = self.client.get('/account/login/')
        self.assertIn('Content-Security-Policy', response)
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn('camera=()', response['Permissions-Policy'])

    # --- Аудит секретов ---
    @override_settings(SECRET_KEY='proper-non-default-secret-key-for-tests-0123456789')
    def test_check_secrets_passes_with_good_config(self):
        # С нормальным SECRET_KEY и DEBUG=True команда завершается без проблем.
        call_command('check_secrets')

    def test_check_secrets_fails_on_default_secret_key(self):
        # Небезопасный ключ по умолчанию должен приводить к ненулевому коду выхода.
        with override_settings(SECRET_KEY='django-insecure-your-secret-key-change-in-production'):
            with self.assertRaises(SystemExit):
                call_command('check_secrets')


import json

from .models import Order, PaymentEvent
from .payments import get_provider


# Тесты платёжного модуля проверяют встроенную sandbox-эмуляцию (HMAC-колбэк),
# поэтому принудительно очищаем реальные ключи провайдеров — иначе ключи из
# локального .env разработчика «протекают» в тесты: оплата уходила бы в реальный
# API PayPal по сети, а колбэк требовал бы настоящей проверки подписи вебхука.
@override_settings(
    BEREKE_SANDBOX=True, PAYPAL_MODE='sandbox', PAYMENT_PUBLIC_BASE_URL='',
    PAYPAL_CLIENT_ID='', PAYPAL_CLIENT_SECRET='', PAYPAL_WEBHOOK_ID='',
    BEREKE_CLIENT_ID='', BEREKE_CLIENT_SECRET='',
)
class PaymentsTests(APITestCase):
    """Тесты платёжного модуля (PAY-002…PAY-006)."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='payer@example.com', password='password123')

    def _checkout(self, provider='bereke', months=1, idem=None):
        self.client.force_authenticate(user=self.user)
        headers = {'HTTP_IDEMPOTENCY_KEY': idem} if idem else {}
        return self.client.post(
            '/api/orders/checkout/',
            {'provider': provider, 'months': months},
            format='json',
            **headers,
        )

    def _signed_callback(self, order, outcome='paid'):
        """Сформировать подписанный payload, как прислал бы провайдер."""
        provider = get_provider(order.provider)
        return provider.build_sandbox_callback(order, outcome)

    # --- PAY-002: сквозной разовый платёж через Bereke sandbox ---
    def test_bereke_end_to_end_activates_subscription(self):
        resp = self._checkout(provider='bereke', months=1)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        order = Order.objects.get(number=resp.data['order_number'])
        self.assertEqual(order.status, Order.STATUS_PENDING)
        self.assertEqual(order.currency, 'KZT')
        self.assertIn('/payments/pay/', resp.data['redirect_url'])

        # Провайдер присылает подписанный колбэк об успешной оплате.
        payload = self._signed_callback(order, 'paid')
        cb = self.client.post(
            '/payments/callback/bereke/', data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(cb.status_code, 200)

        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)
        self.assertIsNotNone(order.paid_at)
        # Подписка пользователя активирована.
        self.user.subscription.refresh_from_db()
        self.assertEqual(self.user.subscription.status, 'active')
        self.assertTrue(self.user.subscription.is_active)

    # --- PAY-003: колбэк-эндпоинт проверяет подпись ---
    def test_callback_rejects_bad_signature(self):
        resp = self._checkout(provider='bereke')
        order = Order.objects.get(number=resp.data['order_number'])

        payload = self._signed_callback(order, 'paid')
        payload['sign'] = 'deadbeef'  # ломаем подпись
        cb = self.client.post(
            '/payments/callback/bereke/', data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(cb.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PENDING)  # статус не изменился

    # --- PAY-004: автомат состояний запрещает недопустимые переходы ---
    def test_state_machine_rejects_invalid_transitions(self):
        order = Order.objects.create(
            user=self.user, amount=5000, currency='KZT', provider='bereke',
            idempotency_key='test-sm-1', subscription_months=1,
        )
        # created → refunded недопустим
        self.assertFalse(order.transition_to(Order.STATUS_REFUNDED))
        self.assertEqual(order.status, Order.STATUS_CREATED)
        # created → pending → paid допустимо
        self.assertTrue(order.transition_to(Order.STATUS_PENDING))
        self.assertTrue(order.transition_to(Order.STATUS_PAID))
        # paid → pending недопустим
        self.assertFalse(order.transition_to(Order.STATUS_PENDING))
        self.assertEqual(order.status, Order.STATUS_PAID)
        # Каждая попытка перехода фиксируется в аудите.
        self.assertTrue(PaymentEvent.objects.filter(order=order, event_type='rejected').exists())

    # --- PAY-005: защита от дублей на checkout ---
    def test_checkout_is_idempotent_with_same_key(self):
        r1 = self._checkout(provider='bereke', months=1, idem='same-key-123')
        r2 = self._checkout(provider='bereke', months=1, idem='same-key-123')
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertFalse(r1.data['reused'])
        self.assertTrue(r2.data['reused'])
        self.assertEqual(r1.data['order_number'], r2.data['order_number'])
        self.assertEqual(Order.objects.filter(user=self.user).count(), 1)

    # --- PAY-005: повторный колбэк не активирует подписку дважды ---
    def test_duplicate_callback_is_idempotent(self):
        resp = self._checkout(provider='bereke')
        order = Order.objects.get(number=resp.data['order_number'])
        payload = self._signed_callback(order, 'paid')

        self.client.post('/payments/callback/bereke/', data=json.dumps(payload), content_type='application/json')
        order.refresh_from_db()
        paid_end_first = order.user.subscription.paid_end

        # Тот же колбэк ещё раз — заказ уже оплачен, подписка не продлевается.
        cb2 = self.client.post('/payments/callback/bereke/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(cb2.status_code, 200)
        self.assertFalse(cb2.json()['changed'])
        order.user.subscription.refresh_from_db()
        self.assertEqual(order.user.subscription.paid_end, paid_end_first)

    # --- PAY-006: международный платёж через PayPal sandbox (USD) ---
    def test_paypal_end_to_end_usd(self):
        resp = self._checkout(provider='paypal', months=2)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        order = Order.objects.get(number=resp.data['order_number'])
        self.assertEqual(order.currency, 'USD')
        self.assertEqual(order.subscription_months, 2)

        payload = self._signed_callback(order, 'paid')
        cb = self.client.post(
            '/payments/callback/paypal/', data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(cb.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)

    # --- PAY-002: отклонённая оплата помечает заказ как failed ---
    def test_declined_payment_marks_order_failed(self):
        resp = self._checkout(provider='bereke')
        order = Order.objects.get(number=resp.data['order_number'])
        payload = self._signed_callback(order, 'failed')
        self.client.post('/payments/callback/bereke/', data=json.dumps(payload), content_type='application/json')
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_FAILED)

    # --- Колбэк по несуществующему заказу возвращает 404 ---
    def test_callback_unknown_order(self):
        order = Order.objects.create(
            user=self.user, amount=5000, currency='KZT', provider='bereke',
            idempotency_key='ghost', provider_order_id='BRK-DOESNOTEXIST',
        )
        payload = self._signed_callback(order, 'paid')
        payload['invoiceId'] = 'BRK-MISSING'
        payload['sign'] = get_provider('bereke').build_signature(payload)
        cb = self.client.post('/payments/callback/bereke/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(cb.status_code, 404)

    # --- Повторная оплата после неудачной попытки активирует подписку ---
    def test_failed_order_can_be_retried_and_paid(self):
        resp = self._checkout(provider='bereke')
        order = Order.objects.get(number=resp.data['order_number'])

        # Первая попытка — отказ: заказ переходит в failed.
        fail_payload = self._signed_callback(order, 'failed')
        self.client.post('/payments/callback/bereke/', data=json.dumps(fail_payload), content_type='application/json')
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_FAILED)

        # Повторный checkout переиспользует тот же заказ и возвращает его в pending.
        resp2 = self._checkout(provider='bereke')
        self.assertTrue(resp2.data['reused'])
        self.assertEqual(resp2.data['order_number'], order.number)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PENDING)

        # Теперь оплата проходит и подписка активируется (раньше переход
        # failed → paid запрещал автомат состояний — оплата «терялась»).
        pay_payload = self._signed_callback(order, 'paid')
        cb = self.client.post('/payments/callback/bereke/', data=json.dumps(pay_payload), content_type='application/json')
        self.assertEqual(cb.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)
        self.user.subscription.refresh_from_db()
        self.assertTrue(self.user.subscription.is_active)

    # --- Оплаченный заказ не блокирует повторную покупку (продление) ---
    def test_paid_order_does_not_block_new_purchase(self):
        resp = self._checkout(provider='bereke')
        order = Order.objects.get(number=resp.data['order_number'])
        pay_payload = self._signed_callback(order, 'paid')
        self.client.post('/payments/callback/bereke/', data=json.dumps(pay_payload), content_type='application/json')
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)

        # Повторная покупка того же тарифа должна создать НОВЫЙ заказ, а не
        # упереться в уникальный idempotency_key уже оплаченного заказа.
        resp2 = self._checkout(provider='bereke')
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(resp2.data['order_number'], order.number)
        self.assertEqual(Order.objects.filter(user=self.user).count(), 2)

    # --- Бесплатная ручная активация PRO недоступна обычному пользователю ---
    def test_manual_activate_forbidden_for_regular_user(self):
        self.client.force_authenticate(user=self.user)
        resp = self.client.post('/api/subscription/activate/', {'months': 12}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.user.subscription.refresh_from_db()
        self.assertNotEqual(self.user.subscription.status, 'active')


from contextlib import contextmanager
from unittest.mock import MagicMock

from .captcha import validate_captcha


def _fake_siteverify(payload):
    """Подменяет ответ Google siteverify заданным JSON."""
    @contextmanager
    def _cm(*args, **kwargs):
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode('utf-8')
        yield resp
    return _cm


@override_settings(
    RECAPTCHA_SITE_KEY='test-site', RECAPTCHA_SECRET_KEY='test-secret',
    RECAPTCHA_VERSION='v3', RECAPTCHA_MIN_SCORE=0.5,
)
class RecaptchaV3Tests(APITestCase):
    """Проверка серверной логики reCAPTCHA v3 (score + action)."""

    def setUp(self):
        self.factory = RequestFactory()

    def _request(self):
        return self.factory.post('/account/login/', {'g-recaptcha-response': 'token'})

    def test_v3_high_score_passes(self):
        result = {'success': True, 'score': 0.9, 'action': 'login'}
        with patch('urllib.request.urlopen', _fake_siteverify(result)):
            self.assertTrue(validate_captcha(self._request(), action='login'))

    def test_v3_low_score_fails(self):
        result = {'success': True, 'score': 0.1, 'action': 'login'}
        with patch('urllib.request.urlopen', _fake_siteverify(result)):
            self.assertFalse(validate_captcha(self._request(), action='login'))

    def test_v3_action_mismatch_fails(self):
        result = {'success': True, 'score': 0.9, 'action': 'register'}
        with patch('urllib.request.urlopen', _fake_siteverify(result)):
            self.assertFalse(validate_captcha(self._request(), action='login'))

    def test_v3_unsuccessful_token_fails(self):
        result = {'success': False, 'error-codes': ['invalid-input-response']}
        with patch('urllib.request.urlopen', _fake_siteverify(result)):
            self.assertFalse(validate_captcha(self._request(), action='login'))

    def test_v3_missing_token_fails_without_network(self):
        request = self.factory.post('/account/login/', {})  # нет g-recaptcha-response
        self.assertFalse(validate_captcha(request, action='login'))

    @override_settings(RECAPTCHA_VERSION='v2')
    def test_v2_success_passes(self):
        result = {'success': True}  # v2 не присылает score
        with patch('urllib.request.urlopen', _fake_siteverify(result)):
            self.assertTrue(validate_captcha(self._request(), action='login'))


@override_settings(RECAPTCHA_SITE_KEY='', RECAPTCHA_SECRET_KEY='')
class ObservabilityTests(APITestCase):
    """Тесты эпика наблюдаемости OPS-002..005: health, метрики, логирование.

    Раньше у всего observability-эпика не было автотестов — формат
    Prometheus-экспозиции и per-request логирование могли молча сломаться.
    """

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def tearDown(self):
        cache.clear()

    # --- OPS-002: детальный health-check (/api/health/) проверяет БД и кеш ---
    def test_health_check_returns_ok(self):
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body['status'], 'healthy')
        self.assertEqual(body['database'], 'ok')
        self.assertEqual(body['cache'], 'ok')

    # --- OPS-002/003: эндпоинт отдаёт валидный Prometheus-формат ---
    def test_prometheus_endpoint_exposes_metrics(self):
        response = self.client.get('/api/metrics/prometheus/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('text/plain', response['Content-Type'])
        body = response.content.decode('utf-8')
        # Должны быть counter'ы (на них строится оконный error rate) и метаданные.
        for needle in ('# HELP', '# TYPE', 'cohub_requests_total', 'cohub_errors_total'):
            self.assertIn(needle, body)

    # --- OPS-003: сводка содержит золотые сигналы ---
    def test_metrics_summary_has_golden_signals(self):
        response = self.client.get('/api/metrics/summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        signals = response.json()['golden_signals']
        for key in ('request_rate', 'error_rate_percent', 'p95_latency_ms'):
            self.assertIn(key, signals)

    # --- Опциональная защита метрик токеном ---
    @override_settings(METRICS_TOKEN='s3cret-token')
    def test_metrics_require_token_when_configured(self):
        denied = self.client.get('/api/metrics/prometheus/')
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        allowed = self.client.get(
            '/api/metrics/prometheus/', HTTP_AUTHORIZATION='Bearer s3cret-token',
        )
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)

        allowed_q = self.client.get('/api/metrics/prometheus/?token=s3cret-token')
        self.assertEqual(allowed_q.status_code, status.HTTP_200_OK)

    # --- OPS-004: ключевой endpoint пишет ровно одну структурную запись ---
    def test_key_endpoint_emits_one_structured_log(self):
        with self.assertLogs('cohub.requests', level='INFO') as captured:
            self.client.get('/api/rooms/')  # /api/ — ключевой префикс
        records = [
            r for r in captured.records
            if getattr(r, 'extra_data', {}).get('event_type') == 'http_request'
        ]
        self.assertEqual(len(records), 1)
        data = records[0].extra_data
        self.assertEqual(data['path'], '/api/rooms/')
        self.assertIn('latency_ms', data)
        self.assertIn('request_id', data)

    # --- OPS-004: 5xx логируется на уровне ERROR (ветка errors.json) ---
    def test_server_error_logs_at_error_level(self):
        from .metrics_middleware import MetricsMiddleware
        middleware = MetricsMiddleware(lambda request: None)
        request = self.factory.get('/api/rooms/')
        request.request_id = 'test-req-id'
        with self.assertLogs('cohub.requests', level='ERROR') as captured:
            middleware._log_request(request, 500, 42.0)
        self.assertEqual(captured.records[0].levelname, 'ERROR')
        self.assertEqual(captured.records[0].extra_data['status_code'], 500)


@override_settings(RECAPTCHA_SITE_KEY='', RECAPTCHA_SECRET_KEY='', POSTHOG_API_KEY='')
class AnalyticsTests(APITestCase):
    """PostHog-аналитика (Week 5): graceful no-op без ключа, identify, KPI, флаги."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('analytics@cohub.local', 'analytics@cohub.local', 'pw12345xZ')
        self.user.first_name = 'Ана'
        self.user.last_name = 'Литик'
        self.user.save()

    # --- Без ключа всё выключено и не падает ---
    def test_disabled_without_key(self):
        from cohub_app import analytics
        self.assertFalse(analytics.analytics_enabled())

    def test_capture_and_identify_are_safe_noops(self):
        from cohub_app import analytics
        # Не должно бросать исключений и не должно ничего слать.
        analytics.identify_user(self.user)
        analytics.capture_event(self.user, 'task_created', {'room_id': 'x'})
        analytics.capture_event(self.user, 'totally_unknown_event', {})

    def test_feature_flag_falls_back_to_default(self):
        from cohub_app import analytics
        self.assertTrue(analytics.feature_enabled('pro-upsell-banner', self.user, default=True))
        self.assertFalse(analytics.feature_enabled('pro-upsell-banner', self.user, default=False))

    # --- Таксономия: >= 10 различных типов событий ---
    def test_event_taxonomy_has_10_plus_types(self):
        from cohub_app import analytics
        self.assertGreaterEqual(len(analytics.EVENTS), 10)
        self.assertIn('payment_completed', analytics.EVENTS)
        self.assertEqual(analytics.FUNNEL_STEPS[0], 'user_signed_up')
        self.assertEqual(analytics.FUNNEL_STEPS[-1], 'payment_completed')

    # --- Person-свойства: email/имя/план для identify ---
    def test_person_properties_contain_email_name_plan(self):
        from cohub_app import analytics
        props = analytics.person_properties(self.user)
        self.assertEqual(props['email'], 'analytics@cohub.local')
        self.assertIn('name', props)
        self.assertIn('plan', props)
        # distinct_id одинаков на сервере и клиенте (по id пользователя).
        self.assertEqual(analytics.distinct_id_for(self.user), str(self.user.id))

    # --- KPI считаются и содержат нужные метрики ---
    def test_compute_kpis_returns_required_metrics(self):
        from cohub_app.views import compute_kpis
        kpi = compute_kpis(period_days=30)
        for key in ('conversion_rate', 'mrr', 'churn_rate', 'arpu', 'total_users'):
            self.assertIn(key, kpi)
        # Без деления на ноль даже при нулевых данных.
        self.assertIsInstance(kpi['conversion_rate'], float)

    # --- Клиентский сниппет не рендерится без ключа (no-op на фронте) ---
    def test_posthog_snippet_absent_when_disabled(self):
        self.client.force_login(self.user)
        resp = self.client.get('/account/')
        self.assertNotIn(b'posthog.init', resp.content)

    # --- KPI-дашборд доступен только админу ---
    def test_kpi_dashboard_requires_admin(self):
        self.client.force_login(self.user)
        resp = self.client.get('/analytics/kpi/')
        self.assertEqual(resp.status_code, 302)  # обычного пользователя редиректит

    # --- MRR сводит разные валюты к KZT (PayPal USD не складывается с Bereke KZT) ---
    @override_settings(USD_TO_KZT_RATE=475)
    def test_compute_kpis_converts_usd_to_kzt(self):
        from decimal import Decimal
        from cohub_app.models import Order
        from cohub_app.views import compute_kpis
        Order.objects.all().delete()  # чистый старт, чтобы число было предсказуемым
        Order.objects.create(
            user=self.user, amount=Decimal('9.99'), currency='USD', provider='paypal',
            status=Order.STATUS_PAID, paid_at=timezone.now(), subscription_months=1,
            idempotency_key='t-usd', description='usd',
        )
        Order.objects.create(
            user=self.user, amount=Decimal('5000'), currency='KZT', provider='bereke',
            status=Order.STATUS_PAID, paid_at=timezone.now(), subscription_months=1,
            idempotency_key='t-kzt', description='kzt',
        )
        kpi = compute_kpis(30)
        # 9.99 * 475 + 5000 = 9745.25 (а НЕ 9.99 + 5000 = 5009.99).
        self.assertAlmostEqual(kpi['mrr'], 9.99 * 475 + 5000, places=1)

    # --- Клиентский сниппет рендерится с ключом и экранирует XSS в имени ---
    @override_settings(POSTHOG_API_KEY='phc_test_key')
    def test_posthog_snippet_present_and_xss_safe(self):
        self.user.first_name = '</script><script>alert(1)</script>'
        self.user.save()
        self.client.force_login(self.user)
        resp = self.client.get('/account/')
        body = resp.content.decode('utf-8', 'ignore')
        self.assertIn('posthog.init', body)
        # Имя пользователя не должно «выйти» из <script> сырым тегом.
        self.assertNotIn('</script><script>alert(1)', body)
