from pydantic import BaseModel, ConfigDict, Field


class WhatsAppWebhookRequest(BaseModel):
    from_number: str = Field(alias="from")
    body: str = ""

    model_config = ConfigDict(populate_by_name=True)


class WhatsAppWebhookResponse(BaseModel):
    to: str
    reply: str
    current_state: str
    outbound: dict | None = None