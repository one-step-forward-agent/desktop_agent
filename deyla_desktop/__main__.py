import sys
if sys.argv[1:2] == ["--document-worker"]:
    from deyla_desktop.document_worker import main
    main(sys.argv[2:])
else:
    from deyla_desktop.app import main
    main()
