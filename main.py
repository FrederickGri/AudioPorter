"""Desktop and isolated downloader entry point (also used by the app bundle)."""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        from audioraven.worker import main
        sys.argv.pop(1)
        raise SystemExit(main())
    elif len(sys.argv) > 1 and sys.argv[1] == "--smoke-test":
        from audioraven.smoke import main
        raise SystemExit(main(sys.argv[2:]))
    else:
        from audioraven.app import main
        main()
