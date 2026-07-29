from django.db import models
from django.db.models import Q

class ProcessedVariant(models.Model):
    sample = models.ForeignKey("library.Sample", on_delete=models.CASCADE, related_name="variants")
    is_current = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sample"],           # ← which field(s)?
                condition=Q(is_current=True),       # ← the "only these rows" filter
                name="unique_current_variant_per_sample",
            )
        ]
