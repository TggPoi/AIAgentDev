from app.services.text_loader import load_text_lines


def main() -> None:
    file_path = "data/sample.txt"
    lines = load_text_lines(file_path)

    for index, line in enumerate(lines):
        print(f"{index}: {line}")


if __name__ == "__main__":
    main()