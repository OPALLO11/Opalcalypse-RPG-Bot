import string


def search_strings(filename, target="points", min_len=4):
    with open(filename, "rb") as f:
        data = f.read()

    result = []
    current_string = []

    for byte in data:
        char = chr(byte)
        if char in string.printable and char not in ('\n', '\r', '\t'):
            current_string.append(char)
        else:
            if len(current_string) >= min_len:
                result.append("".join(current_string))
            current_string = []

    if len(current_string) >= min_len:
        result.append("".join(current_string))

    found = False
    for i, s in enumerate(result):
        if target.lower() in s.lower():
            start = max(0, i - 2)
            end = min(len(result), i + 3)
            print("Match found:", s)
            print("Context:", result[start:end])
            print("---")
            found = True

    if not found:
        print(f"No match for '{target}' found in {filename}")


if __name__ == "__main__":
    search_strings(r"E:\_Live Streaming Work\OPALLO11 - Live Streaming\All Program\Streamerbot\data\globals.db")
    print("\n\n------- USERS.DAT --------")
    search_strings(r"E:\_Live Streaming Work\OPALLO11 - Live Streaming\All Program\Streamerbot\data\users.dat")
