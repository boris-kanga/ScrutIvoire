import asyncio

import pdfplumber
import requests


# print(requests.get("http://62.169.26.22:11434"))

from src.core.logger import setup_logging
from src.repository.llm_repo import LLMRepo
from src.worker import extract_election_name_from_pdf_page_1, \
    find_pdf_utils_columns

test = "/Users/auser/Library/CloudStorage/OneDrive-Personnel/MY-CLOUD/OWN/ScrutIvoire/data/tmp/Résultats-du-second-tour-2010.pdf"
test = "/Users/auser/Library/CloudStorage/OneDrive-Personnel/MY-CLOUD/OWN/ScrutIvoire/data/tmp/Municipales_2023.pdf"
#test = "/Users/auser/Library/CloudStorage/OneDrive-Personnel/MY-CLOUD/OWN/ScrutIvoire/data/tmp/EDAN_2025_RESULTAT_NATIONAL_DETAILS.pdf"
setup_logging()

with pdfplumber.open(test) as pdf:
    page1 = None
    for page in pdf.pages[:1]:
        if page1 is None:
            page1 = page
            name = extract_election_name_from_pdf_page_1(page1)
            table = page.extract_table()
            column = find_pdf_utils_columns(table)
            print(column, name)
            llm = LLMRepo()

            messages = llm.get_prompt(
                "column_detector",
                user_arg=dict(
                    title=name,
                    columns=column,
                ),
                system_arg=dict(
                    title=name
                )
            )
            print(asyncio.run(llm.run(
                "column_detector",
                messages, {}, timeout=5000
            )))
            exit()





if __name__ == '__main__':
    pass