from pydantic import BaseModel
from typing import Optional


class Medication(BaseModel):
    name: str
    dose: str
    frequency: str


class Allergy(BaseModel):
    substance: str
    reaction: str


class LabResult(BaseModel):
    test: str
    value: str
    unit: str
    date: str
    flag: Optional[str] = None


class Patient(BaseModel):
    id: str
    name: str
    age: int
    sex: str
    blood_type: Optional[str] = None
    chief_complaint: str
    diagnoses: list[str]
    medications: list[Medication]
    allergies: list[Allergy]
    lab_results: list[LabResult]
    notes: Optional[str] = None
