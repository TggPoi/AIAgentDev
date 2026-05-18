import sys


def main() -> None:
    for path in sys.path:
        print(path)


if __name__ == "__main__":
    main()


# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.import_path_demo
# D:\AI_Agent_Project\AI_Python_Project\python-agent-study
# D:\AI_Agent_Project\AI_Python_Project\python-agent-study\src
# C:\Users\TGG\AppData\Local\Programs\Python\Python312\python312.zip
# C:\Users\TGG\AppData\Local\Programs\Python\Python312\DLLs
# C:\Users\TGG\AppData\Local\Programs\Python\Python312\Lib
# C:\Users\TGG\AppData\Local\Programs\Python\Python312
# D:\AI_Agent_Project\AI_Python_Project\python-agent-study\.venv
# D:\AI_Agent_Project\AI_Python_Project\python-agent-study\.venv\Lib\site-packages