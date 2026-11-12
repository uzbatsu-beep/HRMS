
from app.database import Base
from app.models import PlatformSetting


def test_platform_settings_table_is_registered() -> None:
    table = Base.metadata.tables["platform_settings"]
    required_columns = {"id", "key", "value", "description", "created_at", "updated_at"}

    assert PlatformSetting.__tablename__ == "platform_settings"
    assert required_columns.issubset(table.columns.keys())
    assert any(
        constraint.name == "uq_platform_settings_key"
        for constraint in table.constraints
    )
