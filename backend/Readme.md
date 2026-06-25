## Preparing the Kubernetes Environment on macOS
## Check if you have Docker installed and run
```sh
brew install kubectl minikube
minikube start --cpus=2 --memory=4096 --driver=docker
```

## Check it

```sh
kubectl get nodes
```

## Change context to Minikube daemon and build docker image

```sh
eval $(minikube docker-env)
minikube image build -t coav-backend:v1 ./backend
```

## Save $CONN_STR env to cluster secrets

```sh
kubectl create secret generic coav-secrets \
  --from-literal=eventhub-cn="$CONN_STR"
```

## Check if created

```sh
kubectl get secret coav-secrets -o yaml
```

## Deploy backend manifest

```sh
kubectl apply -f k8s/deployment.yaml
```

## Check last logs

```sh
kubectl logs deployment/coav-backend-deployment --tail=50 -f
```

## Clear from K8s

```sh
kubectl delete deployment coav-backend-deployment --ignore-not-found=true
kubectl delete secret coav-secrets --ignore-not-found=true
minikube stop
minikube delete --all --purge
docker system prune -a --volumes -f
```

## Go back to main Readme
[Main Readme.me](../Readme.md)