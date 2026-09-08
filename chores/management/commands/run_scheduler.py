import time

from django.core.management.base import BaseCommand

from chores.services import enqueue_scheduled_jobs, run_pending_jobs


class Command(BaseCommand):
    help = "Enqueue and execute persistent household jobs"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=60)

    def handle(self, *args, **options):
        while True:
            created = enqueue_scheduled_jobs()
            completed = run_pending_jobs()
            self.stdout.write(f"Enqueued {created}; completed {completed}")
            if options["once"]:
                return
            time.sleep(max(1, options["interval"]))
