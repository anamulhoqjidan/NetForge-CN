"""Run GUI by default or receiver in a managed subprocess."""
import sys


def main():
    if '--receiver' in sys.argv:
        from server.unified_receiver import main as receiver_main
        receiver_main()
    else:
        from gui.main_window import NetForgeApp
        app = NetForgeApp()
        app.mainloop()


if __name__ == '__main__':
    main()
