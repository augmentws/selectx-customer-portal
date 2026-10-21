from contextlib import contextmanager

from fastapi import HTTPException, status

from app.services import pestpac_connection, tenancy


@contextmanager
def pestpac_errors():
    """Map PestPac-backed bill-to failures to HTTP responses."""
    try:
        yield
    except (tenancy.ConflictError, pestpac_connection.ConnectionNotReadyError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except tenancy.BillToNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None
    except pestpac_connection.PestPacUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
