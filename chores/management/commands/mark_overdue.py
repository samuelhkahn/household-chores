from datetime import date

from django.core.management.base import BaseCommand

from chores.services import mark_overdue_occurrences


class Command(BaseCommand):
    help = "Mark unfinished occurrences before a date as overdue"

    def add_arguments(self, parser):
        parser.add_argument("--as-of", type=date.fromisoformat)

    def handle(self, *args, **options):
        count = mark_overdue_occurrences(as_of=options["as_of"])
        self.stdout.write(self.style.SUCCESS(f"Marked {count} occurrences overdue"))
