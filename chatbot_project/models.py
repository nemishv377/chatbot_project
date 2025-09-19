from django.db import models


class BaseModel(models.Model):
    """
    Abstract base model that provides automatic timestamp fields
    for creation and last update.

    Fields:
        created_at (DateTimeField): Timestamp when the record is created. Automatically set on creation.
        updated_at (DateTimeField): Timestamp when the record is last updated. Automatically updated on each save.

    Notes:
        - This model is abstract and should be inherited by other models.
        - Both fields are indexed for faster query performance based on timestamps.
    """

    created_at = models.DateTimeField(
        auto_now_add=True, blank=True, null=True, db_index=True
    )
    updated_at = models.DateTimeField(
        auto_now=True, blank=True, null=True, db_index=True
    )

    class Meta:
        abstract = True


class DeleteModelMixin(models.Model):
    """
    Abstract mixin to implement soft deletion for models.

    Fields:
        is_deleted (BooleanField): Flag indicating whether the record is considered deleted.
        deleted_at (DateTimeField): Timestamp when the record was marked as deleted. Optional.

    Usage:
        - Instead of permanently deleting records, set `is_deleted=True` and `deleted_at` to current time.
        - Allows recovery or auditing of deleted records.
    """

    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        abstract = True


class ActiveModelMixin(models.Model):
    """
    Abstract mixin to indicate active or inactive status for a model instance.

    Fields:
        is_active (BooleanField): Flag representing whether the record is active or not.

    Usage:
        - Can be used to filter only active records without deleting them.
        - Useful for toggling features, users, or other entities without permanent removal.
    """

    is_active = models.BooleanField(default=False)

    class Meta:
        abstract = True
