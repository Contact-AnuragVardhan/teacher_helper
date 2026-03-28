from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.teacher_repository import TeacherRepository
from app.schemas.teacher import TeacherResponse, TeacherUpsertRequest

router = APIRouter(prefix="/teacher", tags=["teacher"])


@router.get("/{whatsapp_number}", response_model=TeacherResponse)
def get_teacher(whatsapp_number: str, db: Session = Depends(get_db)) -> TeacherResponse:
    teacher = TeacherRepository(db).get_by_whatsapp_number(whatsapp_number)
    if not teacher:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found.")
    return teacher


@router.post("", response_model=TeacherResponse)
def upsert_teacher(payload: TeacherUpsertRequest, db: Session = Depends(get_db)) -> TeacherResponse:
    if payload.preferred_language.strip().lower() != "english":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='For Phase 1, preferred_language must be "English".',
        )
    teacher = TeacherRepository(db).upsert(
        whatsapp_number=payload.whatsapp_number,
        teacher_name=payload.teacher_name.strip(),
        default_grade=payload.default_grade.strip(),
        default_subject=payload.default_subject.strip(),
        preferred_language="English",
    )
    return teacher
