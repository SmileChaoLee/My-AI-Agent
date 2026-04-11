import secrets
import string

def generate_password(length):
    """
    Generate a random password of given length.
    
    Args:
        length (int): The length of the password to be generated.
    
    Returns:
        str: A random password of given length.
    """
    all_characters = string.ascii_letters + string.digits + string.punctuation
    if length < 8:
        print("Password length should be at least 8 characters.")
        return None
    
    password = ''.join(secrets.choice(all_characters) for i in range(length))
    return password

def main():
    length = int(input("Enter the desired password length: "))
    password = generate_password(length)
    
    if password is not None:
        print(f"Generated Password : {password}")

if __name__ == "__main__":
    main()
