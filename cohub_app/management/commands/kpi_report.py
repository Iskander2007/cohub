"""KPI-отчёт в консоль/JSON (Week 5 deliverable: KPI metrics calculated).

Считает conversion rate, MRR, churn, ARPU из реальных данных и печатает их.
Логика расчёта — одна и та же, что и у KPI-дашборда (cohub_app.views.compute_kpis).

Примеры:
    python manage.py kpi_report
    python manage.py kpi_report --days 7 --json
"""

import json

from django.core.management.base import BaseCommand

from cohub_app.views import compute_kpis


class Command(BaseCommand):
    help = 'Печатает продуктовые KPI (conversion rate, MRR, churn, ARPU).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30, help='Период для MRR/оплат, дней (по умолчанию 30).')
        parser.add_argument('--json', action='store_true', help='Вывести результат в формате JSON.')

    def handle(self, *args, **options):
        kpi = compute_kpis(period_days=options['days'])

        if options['json']:
            self.stdout.write(json.dumps(kpi, ensure_ascii=False, indent=2))
            return

        cur = kpi['currency']
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== COHUB KPI (последние {kpi['period_days']} дней) ===\n"))
        self.stdout.write(f"  Conversion rate : {kpi['conversion_rate']}%  ({kpi['pro_users']} PRO из {kpi['total_users']} польз.)")
        self.stdout.write(f"  MRR             : {kpi['mrr']} {cur}")
        self.stdout.write(f"  ARPU            : {kpi['arpu']} {cur}")
        self.stdout.write(f"  Churn rate      : {kpi['churn_rate']}%  ({kpi['cancelled_users']} отменили/истекли)")
        self.stdout.write(f"  Trial users     : {kpi['trial_users']}")
        self.stdout.write(f"  Оплат за период : {kpi['paid_orders_30d']}")
        self.stdout.write(self.style.SUCCESS('\nГотово.\n'))
