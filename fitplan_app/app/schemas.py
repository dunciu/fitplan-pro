from pydantic import BaseModel, Field


class Profile(BaseModel):
    """What the person tells the app. Free-text fields are treated as DATA, never instructions."""
    goal: str = Field(min_length=3, max_length=300, description="e.g. 'run a half marathon', 'swim 1500 m', 'badminton season prep'")
    age: int = Field(ge=8, le=100)
    experience: str = Field("beginner", max_length=40)
    weeks: int = Field(12, ge=4, le=24)
    days_per_week: int = Field(4, ge=2, le=7)
    equipment: str = Field("", max_length=300)
    injuries: str = Field("", max_length=500)
    notes: str = Field("", max_length=800)
    weight_kg: float | None = Field(None, ge=25, le=250)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    plan: str = Field(max_length=60000)
    age: int = Field(ge=8, le=100)
