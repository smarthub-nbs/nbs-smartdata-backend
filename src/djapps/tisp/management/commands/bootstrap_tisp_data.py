from django.core.management import BaseCommand, call_command

from djapps.tisp.models import CensusDataRecord, TispDataValue, TispKnowledgeDocument


class Command(BaseCommand):
    help = (
        "Populate the local TISP cache when it is missing so search works "
        "consistently after a fresh deployment."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Timeout in seconds for each upstream TISP fetch.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Refresh the cache even when it already contains data.",
        )

    def handle(self, *args, **options):
        if not options["force"] and self._cache_is_populated():
            self.stdout.write(self.style.SUCCESS("TISP cache already populated."))
            return

        self.stdout.write("Bootstrapping TISP knowledge cache...")
        try:
            call_command(
                "ingest_nbs_knowledge",
                timeout=options["timeout"],
                verbosity=options["verbosity"],
            )
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(self.style.WARNING(f"TISP bootstrap skipped: {exc}"))
            return

        self.stdout.write(self.style.SUCCESS("TISP knowledge cache refreshed."))

    @staticmethod
    def _cache_is_populated():
        return (
            TispKnowledgeDocument.objects.exists()
            and CensusDataRecord.objects.exists()
            and TispDataValue.objects.exists()
        )
