# FIRST ADD ~/.aws/credentials file!!!

# make sure in the right directory
cd /home/ubuntu/flats/setup

# install requirements
apt-get update
apt-get -y install build-essential python3-dev python3-pip s3fs
pip3 install -r requirements.txt

# add scrapyd etc to path
export PATH=$PATH:~/.local/bin
# add flats to path
export PYTHONPATH="{PYTHONPATH}:/home/ubuntu/flats"

echo 'export PYTHONPATH="$PYTHONPATH:/home/ubuntu/flats"' >> /etc/environment
chmod +x /etc/environment
. /etc/environment

# run scrapyd server in background
nohup scrapyd >/dev/null 2>&1 & 
echo "Scrapyd server is up and running!"

# deploy spider
cd ../spider
scrapyd-deploy local-target -p morizon_spider
cd ../setup

# setup cron jobs
crontab cron_jobs
echo "Successfully added following jobs to schedule:"
cat cron_jobs

# mount s3 in morizon-data
echo "Mounting s3 in ~/morizon-data"
mkdir ~/morizon-data
chmod 600 ~/.aws/credentials
s3fs morizon-data ~/morizon-data -o nonempty -o passwd_file=/home/ubuntu/.aws/credentials -o use_cache=/tmp -o allow_other -o mp_umask=077 -o uid=1000 -o gid=1000


