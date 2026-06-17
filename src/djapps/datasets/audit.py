from djapps.datasets.models import DatasetAuditLog


def log_dataset_event(dataset, action, actor=None, target=None, details=None):
    target_model = dataset._meta.label_lower
    target_id = dataset.id

    if target is not None:
        target_model = target._meta.label_lower
        target_id = getattr(target, "id", None)

    return DatasetAuditLog.objects.create(
        dataset=dataset,
        actor=actor,
        action=action,
        target_model=target_model,
        target_id=target_id,
        details=details or {},
    )
