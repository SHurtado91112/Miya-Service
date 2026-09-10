import strawberry

from miya_server.db.models import User as DBUser


@strawberry.type
class User:
    """The signed-in account.

    Deliberately *not* a relay `Node`, unlike Album/Author/MediaItem. Those are
    library content that any signed-in client may legitimately resolve by global
    id; users are not. Staying off the `node(id:)` interface means there is no
    generic path for one user to fetch another's record.
    """

    id: strawberry.ID
    email: str
    name: str | None
    avatar_url: str | None


def build_user(db_user: DBUser) -> User:
    return User(
        id=strawberry.ID(str(db_user.id)),
        email=db_user.email,
        name=db_user.name,
        avatar_url=db_user.avatar_url,
    )
