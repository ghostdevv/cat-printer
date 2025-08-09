run:
    uv run python3 main.py

install-service:
    ln -s $(pwd)/service/cat-printer.service ~/.config/systemd/user/cat-printer.service
    systemctl --user daemon-reload
    systemctl --user enable cat-printer.service --now
