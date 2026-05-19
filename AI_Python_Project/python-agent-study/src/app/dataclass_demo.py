from dataclasses import dataclass


@dataclass
class User:
    id: str
    name: str
    age: int


def main() -> None:
    user = User(
        id="user_001",
        name="Alice",
        age=18,
    )

    print(user)
    print(user.id)
    print(user.name)
    print(user.age)


if __name__ == "__main__":
    main()