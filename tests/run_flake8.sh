#Run flake8 test on the code base!
flake8 . --count --ignore=F821 --select=E9,F63,F7,F82 --show-source --statistics
flake8 . --count --ignore=F821,W503 --exit-zero --max-complexity=10 --max-line-length=130 --statistics
