import subprocess
import sys
import time

def main():
    print("==================================================")
    print("Starting FX Bot & Dashboard...")
    print("Dashboard: http://localhost:8000")
    print("==================================================")
    
    # Start the Dashboard
    dash_proc = subprocess.Popen([sys.executable, "dashboard.py"])
    
    # Wait a moment to let the server start
    time.sleep(2)
    
    # Start the Trading Bot
    bot_proc = subprocess.Popen([sys.executable, "main.py"])
    
    try:
        # Keep the main thread alive while children run
        dash_proc.wait()
        bot_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        dash_proc.terminate()
        bot_proc.terminate()
        print("Shutdown complete.")

if __name__ == "__main__":
    main()
