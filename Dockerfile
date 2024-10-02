FROM fedora:39

WORKDIR /app

RUN yum -y update
RUN yum -y install ImageMagick-devel 
RUN yum -y install python3 python3-pip
RUN yum clean all

RUN ln -sf /usr/bin/python3 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

RUN pip install --no-cache-dir setuptools

COPY . .

RUN pip install .

CMD ["python", "main.py"]
