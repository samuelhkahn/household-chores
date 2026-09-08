from datetime import date

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from chores.models import Household
from chores.services import generate_occurrences


class Command(BaseCommand):
    help = "Generate a household's chore occurrences for a Monday-based week"

    def add_arguments(self, parser):
        parser.add_argument("household_id", type=int)
        parser.add_argument("week_start", type=date.fromisoformat)

    def handle(self, *args, **options):
        try:
            household = Household.objects.get(pk=options["household_id"])
            occurrences = generate_occurrences(
                household=household, week_start=options["week_start"]
            )
        except Household.DoesNotExist as exc:
            raise CommandError("Household does not exist") from exc
        except ValidationError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(f"Ensured {len(occurrences)} occurrences exist")
        )
