# Propozycja diagramu Excalidraw: Architektura mikroserwisów (Python + PostgreSQL)

## Warstwa 1: Wejściowa
- Klient (browser/app)
- Load Balancer
- API Gateway

## Warstwa 2: Logiczna
- Mikroserwis A (Python)  
- Mikroserwis B (Python)  
- Mikroserwis C (Python)
- Service Discovery (Consul, Eureka lub DNS K8s)
- Message Broker (RabbitMQ/Kafka; opcjonalnie)

## Warstwa 3: Dane
- PostgreSQL A (osobny DB dla mikroserwisu A)
- PostgreSQL B
- PostgreSQL C

## Warstwa 4: Monitoring/Logowanie
- Monitoring (Prometheus/Grafana)
- Centralne Logowanie (ELK/Loki)

## Przepływ (strzałki):
1. Klient → Load Balancer → API Gateway → Mikroserwisy
2. Mikroserwis → własna baza PostgreSQL
3. Każdy mikroserwis ↔ Service Discovery
4. (Opcjonalnie) Mikroserwisy ↔ Broker komunikatów
5. Mikroserwisy/infrastruktura → Monitoring/Logi

Kolory:
- Wejściowa: #cce5ff (jasny niebieski)
- API Gateway: #3399ff
- Mikroserwisy: #ccffcc (zielony)
- Postgresy: #ffd9b3 (pomarańczowy pastel)
- Service Discovery: #bfbfbf
- Monitoring/Logowanie: #e6ccff

---

Stosując powyższą legendę, narysuję teraz diagram w Excalidraw.
