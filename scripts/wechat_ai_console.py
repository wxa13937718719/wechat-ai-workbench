import argparse

import uvicorn

from wechat_ai_control.app import create_app
from wechat_ai_control.models import AppConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token")
    args = parser.parse_args()
    app = create_app(AppConfig(state_dir=args.state_dir, host=args.host, port=args.port, local_token=args.token))
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
