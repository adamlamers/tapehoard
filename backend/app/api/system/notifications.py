from fastapi import APIRouter, HTTPException
from app.api.common import TestNotificationRequest
from app.services.notifications import notification_manager

router = APIRouter(tags=["System"])


@router.post("/notifications/test", operation_id="test_notification")
def test_notification(request_data: TestNotificationRequest):
    """Dispatches a test alert to the provided Apprise URL."""

    if notification_manager.test_notification(request_data.url):
        return {"message": "Notification dispatched successfully."}

    raise HTTPException(status_code=500, detail="Failed to dispatch test alert.")
