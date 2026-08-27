from database import (
    initialize_database,
    get_or_create_user,
    create_watch,
    get_watches_for_user,
    get_watch_for_user,
    delete_watch,
)


def main():
    initialize_database()

    print("🧪 Testing multi-user isolation...\n")

    # Create two test users.
    user_a = get_or_create_user(
        111111111,
        "Test User A"
    )

    user_b = get_or_create_user(
        222222222,
        "Test User B"
    )

    print(f"User A ID: {user_a}")
    print(f"User B ID: {user_b}")

    # Give each user a completely different watch.
    watch_a = create_watch(
        user_id=user_a,
        retailer="flipkart",
        url="https://example.com/product-a",
        target_price=1000,
        product_name="TEST PRODUCT A",
    )

    watch_b = create_watch(
        user_id=user_b,
        retailer="flipkart",
        url="https://example.com/product-b",
        target_price=2000,
        product_name="TEST PRODUCT B",
    )

    print(f"Watch A ID: {watch_a}")
    print(f"Watch B ID: {watch_b}")

    # Retrieve each user's watches.
    watches_a = get_watches_for_user(user_a)
    watches_b = get_watches_for_user(user_b)

    print("\nUser A watches:")
    for watch in watches_a:
        print(watch)

    print("\nUser B watches:")
    for watch in watches_b:
        print(watch)

    # Verify isolation.
    user_a_sees_b = get_watch_for_user(
        user_a,
        watch_b
    )

    user_b_sees_a = get_watch_for_user(
        user_b,
        watch_a
    )

    print("\nIsolation tests:")

    if user_a_sees_b is None:
        print("✅ User A cannot access User B's watch.")
    else:
        print("❌ SECURITY BUG: User A can access User B's watch!")

    if user_b_sees_a is None:
        print("✅ User B cannot access User A's watch.")
    else:
        print("❌ SECURITY BUG: User B can access User A's watch!")

    # Clean up the test watches.
    delete_watch(user_a, watch_a)
    delete_watch(user_b, watch_b)

    print("\n🧹 Test watches deleted.")
    print("🦅 Multi-user isolation test complete.")


if __name__ == "__main__":
    main()