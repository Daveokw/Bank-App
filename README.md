# DAVE Bank - Command-Line Banking Application

A prototype command-line banking application built with **Python** and **SQLite**. This project demonstrates core banking operations including account management, fund transfers, and transaction history — all within an interactive terminal interface.

## Features

- **Account Management** — Sign up with email validation and secure password input
- **Deposits & Withdrawals** — Add or remove funds with real-time balance updates
- **Fund Transfers** — Transfer money to external bank accounts
- **Airtime Purchase** — Buy airtime for any mobile network
- **Bill Payments** — Pay bills (electricity, internet, water, etc.)
- **Transaction History** — View a formatted log of all past transactions

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language  | Python 3   |
| Database  | SQLite (built-in) |
| Auth      | CLI-based password input via `getpass` |

## Getting Started

### Prerequisites

- **Python 3.7+** installed on your machine

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/bank-app.git
   cd bank-app
   ```

2. **Run the application**
   ```bash
   python "bank app.py"
   ```

   That's it! No additional dependencies or database setup required. SQLite creates the database file automatically on first run.

## Usage

```
---------------------------------------------
        Welcome to DAVE Bank
---------------------------------------------
  1. Sign Up
  2. Sign In
  #. Exit
---------------------------------------------
  Option: 1
```

After signing up, you can sign in to access the full menu:

```
---------------------------------------------
  Logged in as: user@example.com
---------------------------------------------
  1. Check Balance
  2. Deposit
  3. Withdraw
  4. Transfer
  5. Buy Airtime
  6. Pay Bills
  7. Transaction History
  8. Sign Out
---------------------------------------------
```

## Project Structure

```
bank-app/
├── bank app.py      # Main application logic
├── README.md        # Project documentation
├── .gitignore       # Git ignore rules
└── requirements.txt # Python dependencies (none required)
```

## Notes

- This is a **prototype / portfolio project** — it is not intended for production use.
- Passwords are stored in plain text for simplicity. A production version would use hashing (e.g., `bcrypt`).
- The SQLite database (`bank_app.db`) is created locally and excluded from version control.

## License

This project is open source and available for educational purposes.
