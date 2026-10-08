from sqlalchemy.orm import Session, joinedload

from auth.jwt import create_access_token
from auth.password import hash_password, verify_password
from models.tenant import Tenant
from models.user import User


class AuthService:
    @staticmethod
    def _get_default_tenant(db: Session) -> Tenant:
        tenant = db.query(Tenant).filter(Tenant.slug == "default").first()
        if tenant is None:
            raise RuntimeError("Default tenant not found. Run init_db() first.")
        return tenant

    @staticmethod
    def register(db: Session, email: str, password: str) -> User:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise ValueError("Email already registered")

        default_tenant = AuthService._get_default_tenant(db)
        user = User(
            email=email,
            password_hash=hash_password(password),
            role="user",
            tenant_id=default_tenant.id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def login(db: Session, email: str, password: str) -> str | None:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return create_access_token(data={"sub": str(user.id)})

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> User | None:
        return db.query(User).options(joinedload(User.tenant)).filter(User.id == user_id).first()
