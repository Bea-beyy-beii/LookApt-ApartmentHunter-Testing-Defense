# Separate from 0002 on purpose: 0002 merges duplicate threads (UPDATE/DELETE),
# and Postgres refuses to ALTER a table in the same transaction
# ("cannot ALTER TABLE ... because it has pending trigger events").
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core_inquiries", "0002_one_thread_per_landlord_and_attachments"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="conversation",
            constraint=models.UniqueConstraint(
                fields=("renter", "landlord"),
                name="one_conversation_per_renter_landlord",
            ),
        ),
    ]