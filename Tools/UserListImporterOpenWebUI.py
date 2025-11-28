# make a tool that takes a list of names (first and last) and returns
# a csv table with this format:
# Name, E-mail, Password <Testen1234>, User
import csv
import random
import string
import sys
from typing import List


def create_user_csv(names: List[str], output_file: str) -> None:
    # Open the output file with explicit UTF-8 encoding so umlauts are written correctly
    with open(output_file, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['Name', 'E-mail', 'Password', 'User'])
        
        # these are german names. for letters with umlauts, we need to ensure proper encoding
        


        for name in names:
            parts = name.split()
            if len(parts) >= 2:
                first_name = parts[0]
                last_name = parts[-1]
            else:
                first_name = parts[0]
                last_name = ''

            # Create a simple, safe local-part for the email address. Replace common
            # German characters so the address contains only ASCII letters.
            local = last_name.lower().replace(' ', '').replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
            if not local:
                local = first_name.lower()

            email = f"{local}@nacken-ingenieure.de"
            password = "Testen1234"
            role = "User"
            writer.writerow([name, email, password, role])


user_list = [
    "Amr Al-Mrayati",
    "Aline Baar",
    "Marius Clemens",
    "David Contzen",
    "Niklas Fischer",
    "Sirko Fischer",
    "Michaela Flach-Kalscheuer",
    "Anne Grootjans",
    "Miriam Haas",
    "Juliane Habets",
    "Marc Heine",
    "Paramet Khamdeewan",
    "Isabel Knops-Dias",
    "Matthias Kufeld",
    "Stefanie Löwenstein",
    "Felix Magiera",
    "Heiko Mrochen",
    "Viktor Nachtigal",
    "Heribert Nacken",  
    "Helin Ntokouslou",
    "Ursula Roskam",
    "Thomas Tokloth",
    ]

create_user_csv(user_list, 'user_list.csv')
print("CSV file 'user_list.csv' created successfully.")