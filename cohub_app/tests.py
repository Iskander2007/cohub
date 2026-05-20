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
            'description': 'Интернет',
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
        response = self.client.post('/account/login/', {
            'email': 'owner@example.com',
            'password': 'password123',
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
