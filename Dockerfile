FROM python:3 
RUN pip install numpy
ADD https://raw.githubusercontent.com/adengle/adventure/refs/heads/main/advent.py /opt/adv/
ADD https://raw.githubusercontent.com/adengle/adventure/refs/heads/main/text /opt/adv/
WORKDIR /opt/adv
CMD ["python", "advent.py"]
