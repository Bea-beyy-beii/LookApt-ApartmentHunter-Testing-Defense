from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_alter_user_table_landlord_renter"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="notifications_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="theme",
            field=models.CharField(
                choices=[("light", "Light"), ("dark", "Dark")],
                default="light",
                max_length=5,
            ),
        ),
    ]