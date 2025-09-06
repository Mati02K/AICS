# AICS ( AUTO INCIDENT CONTROL SYSTEM)

Install Kubernetes and kind and the follow the below steps

```
kind create cluster --name aics

# build your image (if you haven’t)
docker build -t shoppingapi:0.1 .
kind load docker-image shoppingapi:0.1 --name aics

cd mcp
docker build -t mcp-server:0.1 -f Dockerfile.server .
docker build -t mcp-client:0.1 -f Dockerfile.client .
kind load docker-image mcp-server:0.1 --name aics
kind load docker-image mcp-client:0.1 --name aics

# deploy and watch
cd..
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/pg-secret.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/api-deploy.yaml

# Deploy Ollama
kubectl -n ops apply -f k8s/ollama.yaml
kubectl -n ops rollout status deploy/ollama

# Pull a model into the Ollama pod ONCE (fastest, explicit)
kubectl -n ops get pods -l app=ollama # get the pod name
kubectl -n ops exec -it <THE-OLLAMA-POD-NAME> -- ollama pull qwen2.5:1.5b-instruct

kubectl -n ops apply -f k8s/mcp-server.yaml
kubectl -n ops apply -f k8s/mcp-server-rbac.yaml
kubectl -n ops apply -f k8s/mcp-client.yaml


# Get status
kubectl -n ops rollout status deploy/api
kubectl -n ops rollout status deploy/mcp-server
kubectl -n ops rollout status deploy/mcp-client
kubectl -n ops get pods -w
kubectl -n ops get svc -w


#Port forwards
kubectl -n ops port-forward deploy/api 8000:8000

# Watch logs from the client (you should see LLM plan + exec)
kubectl -n ops logs deploy/mcp-client -f

# In case of any crash
kubectl -n ops logs api-699676456-bfg6v -c api --previous --tail=200

```

Readme on progress will add more once chaos testing is added.