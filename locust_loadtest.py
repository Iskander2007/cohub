"""
Locust load testing script для COHUB.

Сценарий имитирует до 100 одновременных пользователей:
  on_start  -> регистрация (с решением CAPTCHA и CSRF) = авто-вход
  далее     -> просмотр комнат / создание комнаты / расходы / задачи /
               health / метрики (со взвешенными вероятностями).

Скрипт самодостаточен и работает против НЕМОДИФИЦИРОВАННОГО приложения:
  • берёт CSRF-токен из cookie `csrftoken` и шлёт его и в форму, и в заголовке
    X-CSRFToken (DRF SessionAuthentication требует CSRF на небезопасных методах);
  • решает встроенную арифметическую CAPTCHA («Сколько будет A + B?»),
    распарсив вопрос со страницы регистрации;
  • использует реальные поля форм (full_name/email/password/password_confirm/terms).

Запуск (headless, со 100 пользователями и HTML-отчётом):
  locust -f locust_loadtest.py --headless \
         --users 100 --spawn-rate 10 --run-time 2m \
         --host http://127.0.0.1:8000 \
         --html loadtest_report.html

Либо через готовые раннеры: loadtest/run_loadtest.ps1 (Windows) или
loadtest/run_loadtest.sh (Linux/macOS).
"""

import random
import re
import string
from datetime import datetime

from locust import HttpUser, task, between, events

# Из вопроса CAPTCHA «Сколько будет 3 + 5?» достаём оба числа.
CAPTCHA_RE = re.compile(r'(\d+)\s*\+\s*(\d+)')


def _rand_suffix(n: int = 10) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))


class CohubUser(HttpUser):
    """Имитирует поведение пользователя COHUB."""

    # Пауза между действиями одного пользователя (имитация «думающего» юзера).
    wait_time = between(1, 3)

    def on_start(self):
        """Регистрация нового пользователя = авто-вход (сессия + CSRF)."""
        self.email = f"loadtest_{_rand_suffix()}@test.cohub.local"
        self.password = "LoadTest123!secure"
        self.full_name = "Load Test User"
        self.room_id = None
        self.authenticated = False
        self.register()

    # ---------------------------------------------------------------- helpers
    @property
    def csrftoken(self) -> str:
        """Текущее значение cookie csrftoken (нужно для небезопасных запросов)."""
        return self.client.cookies.get('csrftoken', '')

    def _csrf_headers(self) -> dict:
        return {
            'X-CSRFToken': self.csrftoken,
            'Referer': self.host,
        }

    @staticmethod
    def _solve_captcha(html: str) -> str:
        """Достаёт «A + B» из HTML страницы регистрации и считает сумму."""
        match = CAPTCHA_RE.search(html or '')
        if match:
            return str(int(match.group(1)) + int(match.group(2)))
        return ''

    # ------------------------------------------------------------- auth flow
    def register(self):
        """GET формы (CSRF + CAPTCHA) -> POST регистрации -> авто-вход."""
        # 1) GET страницы: получаем cookie csrftoken и текст CAPTCHA.
        with self.client.get('/register/', catch_response=True, name='/register/ [GET]') as resp:
            if resp.status_code != 200:
                resp.failure(f"Register page GET failed: {resp.status_code}")
                return
            resp.success()
            captcha_answer = self._solve_captcha(resp.text)

        # 2) POST формы регистрации (реальные поля + CSRF + решённая CAPTCHA).
        with self.client.post(
            '/register/',
            data={
                'full_name': self.full_name,
                'email': self.email,
                'password': self.password,
                'password_confirm': self.password,
                'terms': 'on',
                'captcha': captcha_answer,
                'csrfmiddlewaretoken': self.csrftoken,
            },
            headers=self._csrf_headers(),
            allow_redirects=False,            # успех = 302 на dashboard
            catch_response=True,
            name='/register/ [POST]',
        ) as resp:
            # 302 -> регистрация прошла и пользователь залогинен.
            if resp.status_code in (302, 303):
                self.authenticated = True
                resp.success()
            else:
                # 200 = форма вернулась с ошибками (например, не прошла CAPTCHA):
                # пользователь НЕ аутентифицирован, поэтому это честный провал —
                # иначе последующие 403 на /api/ выглядели бы беспричинными.
                resp.failure(f"Registration not completed: {resp.status_code}")

    # ------------------------------------------------------------------ tasks
    @task(10)
    def view_rooms(self):
        """Список комнат (основной экран дашборда)."""
        with self.client.get('/api/rooms/', catch_response=True, name='/api/rooms/ [list]') as resp:
            if resp.status_code == 200:
                resp.success()
                try:
                    results = resp.json().get('results') or []
                    if results:
                        self.room_id = results[0]['id']
                except Exception:
                    pass
            else:
                resp.failure(f"List rooms failed: {resp.status_code}")

    @task(5)
    def create_room(self):
        """Создание новой комнаты (write, требует CSRF)."""
        with self.client.post(
            '/api/rooms/',
            # `code` обязателен в сериализаторе (хотя реальный код комнаты сервер
            # генерирует сам в perform_create) — шлём заглушку, чтобы пройти валидацию.
            json={
                'name': f"Room_{random.randint(1000, 9999)}",
                'description': 'load test',
                'code': _rand_suffix(6).upper(),
            },
            headers=self._csrf_headers(),
            catch_response=True,
            name='/api/rooms/ [create]',
        ) as resp:
            if resp.status_code in (200, 201):
                resp.success()
                try:
                    self.room_id = resp.json().get('id', self.room_id)
                except Exception:
                    pass
            elif resp.status_code == 429:
                resp.success()  # троттлинг под нагрузкой — ожидаемое поведение
            else:
                resp.failure(f"Create room failed: {resp.status_code}")

    @task(8)
    def view_room_details(self):
        """Детали конкретной комнаты."""
        if not self.room_id:
            return
        with self.client.get(
            f'/api/rooms/{self.room_id}/',
            catch_response=True,
            name='/api/rooms/{id}/ [detail]',
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Room detail failed: {resp.status_code}")

    @task(6)
    def add_expense(self):
        """Добавление расхода в комнату (write, требует CSRF)."""
        if not self.room_id:
            return
        with self.client.post(
            '/api/expenses/',
            json={
                'room': self.room_id,
                'description': f"Expense_{random.randint(1000, 9999)}",
                'amount': round(random.uniform(100, 5000), 2),
            },
            headers=self._csrf_headers(),
            catch_response=True,
            name='/api/expenses/ [create]',
        ) as resp:
            if resp.status_code in (200, 201, 400, 429):
                # 400 — бизнес-валидация (нет прав в комнате); 429 — троттлинг.
                # Ни то, ни другое не является системным отказом.
                resp.success()
            else:
                resp.failure(f"Add expense failed: {resp.status_code}")

    @task(4)
    def view_expenses(self):
        """Список расходов."""
        with self.client.get('/api/expenses/', catch_response=True, name='/api/expenses/ [list]') as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"List expenses failed: {resp.status_code}")

    @task(3)
    def view_tasks(self):
        """Список задач."""
        with self.client.get('/api/tasks/', catch_response=True, name='/api/tasks/ [list]') as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"List tasks failed: {resp.status_code}")

    @task(2)
    def health_check(self):
        """Проверка живости (используется и мониторингом)."""
        with self.client.get('/health/', catch_response=True, name='/health/') as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Health check failed: {resp.status_code}")

    @task(1)
    def view_metrics(self):
        """Сводка метрик (золотые сигналы)."""
        with self.client.get('/api/metrics/summary/', catch_response=True, name='/api/metrics/summary/') as resp:
            if resp.status_code in (200, 429):  # 429 — троттлинг, ожидаемо под нагрузкой
                resp.success()
            else:
                resp.failure(f"Metrics failed: {resp.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print(f"\n{'=' * 60}")
    print(f"COHUB Load Test START: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Target host: {environment.host}")
    print(f"{'=' * 60}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.stats.total
    print(f"\n{'=' * 60}")
    print(f"COHUB Load Test FINISH: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}")
    print("\nРЕЗУЛЬТАТЫ:")
    print(f"   Всего запросов:        {stats.num_requests}")
    print(f"   Ошибок:                {stats.num_failures}")
    success = stats.num_requests - stats.num_failures
    rate = (success / stats.num_requests * 100) if stats.num_requests else 0.0
    print(f"   Успешных:              {success}")
    print(f"   Успешность:            {rate:.2f}%")
    print(f"   Среднее время ответа:  {stats.avg_response_time:.2f} ms")
    try:
        print(f"   p95:                   {stats.get_response_time_percentile(0.95):.2f} ms")
    except Exception:
        pass
    print(f"   Макс. время ответа:    {stats.max_response_time:.2f} ms")
