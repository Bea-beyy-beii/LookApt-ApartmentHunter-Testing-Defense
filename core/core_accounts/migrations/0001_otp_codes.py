from django.db import migrations, models

class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="OTPCode",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "purpose",
                    models.CharField(
                        choices=[("signup", "Sign up"), ("reset", "Reset password")],
                        max_length=10,
                    ),
                ),
                (
                    "channel",
                    models.CharField(
                        choices=[("sms", "SMS"), ("email", "Email")], max_length=10
                    ),
                ),
                ("target", models.CharField(max_length=254)),
                ("code_hash", models.CharField(max_length=128)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["purpose", "target", "-created_at"],
                        name="core_accoun_purpose_2b64a2_idx",
                    )
                ],
            },
        ),
    ]