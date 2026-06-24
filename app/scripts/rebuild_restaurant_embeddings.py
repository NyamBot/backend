from __future__ import annotations

import argparse

from app.services.restaurant_store import restaurant_store


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild restaurant search embeddings.")
    parser.add_argument(
        "--restaurant-id",
        help="Rebuild only one restaurant. Rebuilds every restaurant when omitted.",
    )
    args = parser.parse_args()

    updated_count = restaurant_store.rebuild_search_embeddings(args.restaurant_id)
    target = args.restaurant_id or "all restaurants"
    print(f"Rebuilt {updated_count} restaurant note embeddings for {target}.")


if __name__ == "__main__":
    main()
