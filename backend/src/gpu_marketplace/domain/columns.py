from sqlalchemy import text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

# Shared column types and server defaults (GPU-002-A matrix section 1). Default timestamps use
# clock_timestamp() so they reflect the real database clock instead of the transaction start.
TIMESTAMPTZ = TIMESTAMP(timezone=True, precision=6)
UUID_PK = UUID(as_uuid=True)
NOW = text("clock_timestamp()")
NEW_UUID = text("gen_random_uuid()")
