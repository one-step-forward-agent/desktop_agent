"""Entry point for running from source and for PyInstaller: python run.py"""

if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["--document-worker"]:
        from deyla_desktop.document_worker import main
        main(sys.argv[2:])
    else:
        from deyla_desktop.app import main
        main()
