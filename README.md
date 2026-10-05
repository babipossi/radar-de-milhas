# Radar de Milhas

Página pessoal que acompanha, todos os dias:

- **Milhas:** assentos-prêmio saindo de Guarulhos para 13 destinos (Seats.aero Pro).
- **Dinheiro:** ida e volta GRU ⇄ Bangalore via Doha e via Frankfurt (Google Flights, pelo plano grátis do SerpApi).

## Como funciona

```
GitHub Actions
  ├─ 07:00 de Brasília: milhas + 7 buscas de ida e volta (4 favoritas + 3 em rodízio)
  ├─ 19:00 de Brasília: só milhas (não gasta SerpApi)
  └─ botão "Atualizar agora" da página: só milhas, ou tudo
  └─ scripts/update_data.py
       ├─ Seats.aero  → milhas (ida e volta separadas)
       └─ SerpApi     → ida e volta em dinheiro + saldo de buscas do mês
  └─ salva docs/data.json no repositório
GitHub Pages
  └─ publica docs/index.html, que lê docs/data.json
```

As chaves das APIs ficam guardadas como *secrets* do GitHub. Elas nunca aparecem na página nem no código.

## O que ajustar e onde

Tudo fica no `config.json`:

| O quê | Campo |
|---|---|
| Datas das milhas | `miles.windows` |
| Datas e conexões da ida e volta | `roundtrip.windows`, `roundtrip.via` |
| Buscas por dia no SerpApi | `roundtrip.dailyFavorites` + `roundtrip.dailyRotation` (hoje 4 + 3 = 7, ~210 por mês) |
| Destinos das milhas e preço de referência | `routes` |
| Custo do milheiro por programa | `programs` |
| Regras de destaque (e, depois, dos alertas) | `alerts` |

O plano grátis do SerpApi dá 250 buscas por mês. Mantenha `dailyFavorites + dailyRotation` em no máximo 8.

As configurações da própria página valem só no navegador em que foram feitas. Para mudar de vez, edite o `config.json`.

## Passo a passo da instalação

### 1. Criar o repositório

1. No GitHub, crie um repositório novo (por exemplo `radar-de-milhas`). Para usar o GitHub Pages no plano gratuito, ele precisa ser **público**. Não há nada pessoal nele, só preços de voos e a configuração.
2. Envie os arquivos desta pasta para o repositório.

### 2. Guardar as chaves

Em **Settings → Secrets and variables → Actions → New repository secret**, crie:

- `SEATS_AERO_KEY`: a chave da API do Seats.aero Pro (em seats.aero, nas configurações da conta, seção API; começa com `pro_`).
- `SERPAPI_KEY`: a chave do SerpApi (em serpapi.com, depois de criar a conta grátis, em *Your Account → API Key*).

Sem uma das chaves, a parte dela simplesmente mantém os dados anteriores.

### 3. Ligar a página

Em **Settings → Pages**, escolha *Deploy from a branch*, branch `main`, pasta `/docs`. Em um ou dois minutos, a página fica disponível no endereço que o GitHub mostrar ali.

### 4. Rodar pela primeira vez

Em **Actions → Atualizar dados → Run workflow**, escolha `tudo`. Depois disso, ela roda sozinha às 7h e às 19h. Cada execução com `tudo` gasta 7 das 250 buscas do mês no SerpApi; `milhas` não gasta nada.

### 5. Botão "Atualizar agora" (opcional)

O botão da página precisa de um token do GitHub que só consiga rodar o robô deste repositório:

1. Em github.com, **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Nome: `radar-botao`. Validade: até o fim da viagem.
3. **Repository access:** *Only select repositories* → este repositório.
4. **Permissions → Repository permissions → Actions:** *Read and write*. Não marque mais nada.
5. Gere, copie o token e cole na página, no campo do painel "Atualizar agora". Ele fica salvo só naquele navegador; repita em cada aparelho.

Com esse token, a única coisa possível é disparar o robô. Ele não lê nem altera arquivos, chaves ou outros repositórios. Se perder o aparelho, apague o token no GitHub.

## Testar no computador

```bash
# Dados de exemplo, sem gastar nenhuma busca
python3 scripts/update_data.py --sample

# Com as chaves de verdade
SEATS_AERO_KEY=pro_xxx SERPAPI_KEY=xxx python3 scripts/update_data.py

# Ver a página
python3 -m http.server --directory docs 8000
# e abrir http://localhost:8000
```

## Limitações conhecidas

- O Seats.aero não cobre o LATAM Pass. Quando aparecer assento da Qatar, a página lembra de cotar também na tabela fixa pelo WhatsApp da LATAM.
- Alguns programas (Qatar, Turkish, Singapore) não informam taxas pelo Seats.aero. Nesses casos, aparece "taxas n/d" e o cálculo considera taxa zero.
- O Seats.aero mostra dados em cache, que podem ter algumas horas. Confirme no site do programa antes de comprar ou transferir pontos.
- Na ida e volta, a conexão é identificada pela escala da ida. A volta costuma seguir pela mesma companhia, mas confirme no Google Flights.
