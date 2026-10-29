# Café Aroma do Sul | Gestão

ERP modular de homologação para cafeteria e restaurante, feito com Python, Streamlit, SQLAlchemy e SQLite.

## Executar

Requer Python 3.10 ou superior.

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m streamlit run app.py
```

O banco padrão é `cafeteria.db` ao lado de `app.py`, independentemente do diretório de onde o Streamlit for iniciado. Um arquivo `cafeteria.db` encontrado em outro diretório de execução bloqueia a inicialização para evitar abrir silenciosamente um banco vazio; nesse caso, configure `DATABASE_URL` explicitamente para o arquivo que contém o histórico. O banco configurado é criado na primeira execução; o aplicativo não insere dados fictícios nesse banco automaticamente. Use `DATABASE_URL` para apontar para PostgreSQL ou outro banco suportado pelo SQLAlchemy.

Com `APP_ENV=production`, o app bloqueia inicialização com SQLite no banco operacional e exige `DATABASE_URL` explícita em PostgreSQL/Supabase.

### Backups do banco operacional

Para SQLite, o aplicativo cria snapshots consistentes e verifica sua integridade a cada intervalo de 15 minutos de uso, mantendo até 96 cópias automáticas (aproximadamente 24 horas). O diretório padrão é `backups/`, ao lado de `app.py`; configure `BACKUP_DIRECTORY` para outro destino persistente. `BACKUP_RETENTION_COUNT` altera o limite de cópias e precisa ser maior que zero. Se o backup automático falhar, a inicialização é interrompida com o erro em vez de continuar silenciosamente sem a proteção configurada. A tela **Configurações → Proteção do banco de dados** mostra o snapshot mais recente e permite baixar uma cópia atual; a exportação é registrada na auditoria.

O diretório padrão está no mesmo computador do banco e, portanto, não protege contra perda ou indisponibilidade desse computador. Para operação real, configure `BACKUP_DIRECTORY` em armazenamento independente (por exemplo, volume de rede com acesso restrito) e mantenha cópias fora do local. Faça e documente testes periódicos de restauração. Backups incluem dados pessoais e financeiros: restrinja permissões e não os envie ao repositório.

Para PostgreSQL ou outro banco externo, o mecanismo de snapshots SQLite não se aplica; veja a seção **PostgreSQL (Supabase)** abaixo.

## PostgreSQL (Supabase)

### Configuração da conexão

`DATABASE_URL` é lida primeiro das variáveis de ambiente e, se ausente, dos segredos do Streamlit (`.streamlit/secrets.toml` localmente ou **Settings → Secrets** na plataforma). O mesmo vale para `MODO_HOMOLOGACAO` e `MODO_DEMONSTRACAO`. Exemplo de `.streamlit/secrets.toml` (já ignorado pelo Git; veja `.env.example`):

```toml
DATABASE_URL = "postgresql://postgres:SENHA@db.<projeto>.supabase.co:5432/postgres"
MODO_HOMOLOGACAO = "false"
```

O prefixo `postgresql://` é convertido automaticamente para o driver `psycopg` (v3). Se a senha tiver `@`, `#`, `/` ou `%`, codifique-a em URL (`@` → `%40`). A conexão direta do Supabase usa IPv6; se a hospedagem não suportar IPv6, use a string do **Session pooler**. Não use o Transaction pooler com este app. Nunca coloque a chave `service_role` no Streamlit nem no Git.

### Schema e migrações

```powershell
py -3 -m alembic upgrade head
```

Aplica as revisões: `0001` (baseline), `0002` (colunas monetárias em `NUMERIC(12,2)` no PostgreSQL, arredondando para centavos) e `0003` (tabela `backup_execucoes`). Em banco novo as tabelas já nascem com os tipos corretos.

### Migrar o SQLite existente

```powershell
$env:DATABASE_URL = "postgresql://postgres:SENHA@host:5432/postgres"
py -3 scripts/migrate_sqlite_to_postgres.py --source cafeteria.db
```

O script salva uma cópia da origem em `backups/pre-migracao-*.sqlite3`, recusa destino que já tenha dados, grava tudo em uma única transação, acerta as sequências de ids e compara contagem de linhas e soma monetária de cada tabela. Qualquer divergência desfaz a gravação. Mantenha o `cafeteria.db` original intacto até concluir o piloto.

### Backup externo criptografado

`scripts/backup_postgres.py` gera `pg_dump` (schema `public`), valida com `pg_restore --list`, criptografa (Fernet/AES) com `BACKUP_ENCRYPTION_KEY`, envia ao bucket **privado** `database-backups` do Supabase Storage, baixa e compara o arquivo enviado, aplica a retenção (último de cada dia por 30 dias, de cada semana por 12 semanas e de cada mês por 12 meses; nunca menos de 3 cópias) e registra a execução em `backup_execucoes`. As Configurações exibem o último backup e alertam se passar de 26 horas.

Preparação (uma vez):

1. Em Supabase → Storage, crie o bucket `database-backups` **privado**.
2. Gere a chave de criptografia e guarde-a em cofre de senhas, separada do projeto (sem ela o backup é irrecuperável):
   `py -3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
3. No GitHub → Settings → Secrets and variables → Actions, cadastre `DATABASE_URL` (Session pooler), `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` e `BACKUP_ENCRYPTION_KEY`.
4. O workflow `.github/workflows/backup.yml` roda diariamente às 02:00 (Brasília) e também sob demanda em **Actions → Run workflow**. Ajuste a versão do `postgresql-client` se o seu projeto Supabase não for PostgreSQL 17.

Restauração de teste (nunca sobre a produção):

```powershell
$env:BACKUP_ENCRYPTION_KEY = "<chave>"
py -3 scripts/restore_postgres_backup.py --file cafeteria-AAAAMMDD-HHMMSS.dump.enc --target "postgresql://...banco-de-teste"
```

Confira contagens e totais de vendas no banco de teste. Repita o teste ao menos uma vez por mês e ative também os backups nativos do plano Supabase.

## Homologação e produção

`MODO_HOMOLOGACAO = True` mantém o login desativado, permissões ignoradas e registra operações com `SISTEMA_HOMOLOGACAO`. Para ativar o login, defina `MODO_HOMOLOGACAO=False` em `config.py` ou use a variável de ambiente `MODO_HOMOLOGACAO=false`. Na primeira abertura será solicitado o cadastro do administrador. Perfis e permissões são inicializados no banco; o módulo administrativo de usuários permanece oculto até `MODULO_USUARIOS=True`.

No modo com login ativo, a sessão autenticada usa token opaco persistido em cookie com `Secure` e `SameSite` configuráveis (`AUTH_COOKIE_SECURE`, `AUTH_COOKIE_SAMESITE`) e renovação deslizante por `AUTH_SESSION_TTL_DAYS`. O logout revoga a sessão no banco e remove o cookie.

`MODO_DEMONSTRACAO=true` seleciona um arquivo SQLite separado (`cafeteria_demo.db`, configurável por `DEMO_DATABASE_URL`) e exibe um selo global. A configuração recusa banco em memória e impede que o caminho coincida com `DATABASE_URL`. Em Configurações, **Popular Dados de Demonstração** substitui somente os dados desse arquivo, gerando catálogo, estoque, pedidos, caixa e financeiro dos últimos 90 dias. O modo fica desativado por padrão; o app não semeia mais registros demonstrativos automaticamente no banco principal. `MODO_HOMOLOGACAO` controla login/permissões e é independente do modo de dados.

Para ativar no PowerShell:

```powershell
$env:MODO_DEMONSTRACAO = "true"
py -3 -m streamlit run app.py
```

Com o modo ativo, **Configurações → Homologação** oferece geração, limpeza, reset e transferência do banco demonstrativo. A geração e a limpeza atuam somente nesse SQLite separado; a limpeza e o reset exigem digitar `CONFIRMAR`, criam um backup automático e removem apenas registros identificados com `demo=True`. Usuários, perfis, permissões e auditorias não marcadas como demo são preservados, e cada limpeza é registrada na auditoria. Registros de versões anteriores que não tenham essa identificação não são apagados; conflitos com dados não identificados bloqueiam operações que poderiam sobrescrevê-los. A importação valida o arquivo e também recusa substituir dados operacionais sem identificação demo. Use **Exportar Backup** para baixar uma cópia antes de transferir dados entre ambientes.

Datas e horários de negócio usam `APP_TIMEZONE`, com padrão `America/Sao_Paulo`. Os valores são gravados como horários locais sem informação de fuso na coluna SQLite; dados antigos são preservados e interpretados conforme o fuso configurado, sem conversão retroativa.

Os módulos de Financeiro, DRE e Inteligência são controlados por flags em `config.py`. NFe e WhatsApp estão desabilitados nesta versão.

## Navegação

A tela inicial prioriza tarefas operacionais e mostra apenas os estados permitidos pelo perfil ativo; o menu superior não repete os atalhos de operação já disponíveis no início. Indicadores financeiros e a visão geral ficam na área de Gestão, acessível conforme as permissões. A projeção de fluxo de caixa fica no módulo Financeiro; Relatórios mantém consultas históricas e análises por período.

Quando um pedido é finalizado na cozinha, o sistema abre uma comanda vinculada ao cliente. A área **Comandas** reúne as contas abertas; é possível adicionar pedidos à comanda (cada novo lote volta à fila da cozinha) e fechar/cobrar quando todos os pedidos estiverem finalizados e houver caixa aberto. O recebimento é registrado como entrada no caixa com a forma de pagamento escolhida. Em telas menores, o seletor de navegação continua oferecendo os módulos autorizados.

Novos pedidos exigem **caixa aberto** (inclusive ao adicionar pedido em comanda). Com o caixa fechado, a interface bloqueia a operação e orienta abrir um turno primeiro, preservando a integridade financeira.

Pedidos compostos apenas por itens sem preparo (sem ficha técnica de cozinha ou com ficha de autoconsumo) são finalizados automaticamente com baixa de estoque imediata, evitando envio desnecessário para a cozinha.

Após o fechamento de caixa, o módulo **Caixa** disponibiliza exportação em Excel com movimentação detalhada por item (data, hora, produto, quantidade, valor unitário, valor total, forma de pagamento) e resumo financeiro do turno.

No modo com login, a sessão autenticada agora persiste por até 14 dias com renovação de atividade, reduzindo novos logins em acessos móveis sem remover o fluxo de logout.

O tema compartilhado define cores escuras de alto contraste para valores, rótulos, botões, campos e mensagens, incluindo os indicadores da página inicial e da visão geral. O tema e a marca visual do Café Aroma do Sul são configurados em `.streamlit/config.toml` e `components/layout.py`.

## Base de demonstração no PostgreSQL

`scripts/demo_banco.py` gera, valida, resume e remove uma base demonstrativa completa (90 dias: 24 clientes, 15 produtos e 9 insumos com ficha técnica, estoque, ~3,8 mil pedidos com itens, cancelamentos, comandas, caixa diário, fluxo de caixa, contas a pagar e a receber e auditoria) no banco configurado em `DATABASE_URL`:

```powershell
py -3 scripts/demo_banco.py carregar --confirmar   # gera e valida (bloqueia se houver dados reais)
py -3 scripts/demo_banco.py validar                # confere a integridade
py -3 scripts/demo_banco.py resumo                 # registros por tabela
py -3 scripts/demo_banco.py limpar --confirmar     # limpar_dados_demo()
```

Cada registro criado recebe um marcador na tabela `registros_demo` (entidade + id) e os textos livres levam o rótulo `DADOS DE DEMONSTRAÇÃO`. `limpar_dados_demo()` (`services/demo_operacoes.py`) remove somente os registros marcados, em uma única transação, e preserva estrutura, usuários, perfis, permissões, auditoria de login, configurações e qualquer dado real; se algum registro real referenciar dados demo, a limpeza é bloqueada. **Execute `limpar` antes de migrar o histórico real** (a migração exige um destino sem dados). A carga leva alguns minutos no Supabase por causa da latência de rede.

## Estrutura

- `models/`: entidades e tabelas SQLAlchemy.
- `database/`: conexão, sessões e criação do schema.
- `services/`: autenticação, regras operacionais e dados demonstrativos.
- `pages/`: módulos Streamlit.
- `components/`: layout e QR code de pedidos.
- `utils/`: formatação e utilitários.
- `tests/`: testes dos fluxos operacionais, backup e central de homologação.
- `alembic/`: migrações versionadas do banco de dados.
- `scripts/`: migração SQLite→PostgreSQL, backup criptografado e restauração de teste.
- `.github/workflows/`: automação do backup diário.
- `utils/money.py`: normalização monetária e arredondamento de centavos.
- `services/database_backup.py` e `services/database_health.py`: proteção e diagnóstico do SQLite.

Para abrir pedidos em um celular, inicie o Streamlit em um endereço de rede acessível e informe a URL no expansor de QR code do módulo Pedidos.

## Observações da versão

Esta entrega é uma base funcional para homologação, não substitui configuração operacional ou validação fiscal. Descontos e impostos da DRE ainda aparecem zerados até parametrização; a projeção usa saldo do caixa e contas a pagar/receber cadastradas, sem incorporar vendas automaticamente. CMV, DRE e margem de produto usam o custo calculado pela ficha técnica quando ela existe e o custo cadastrado do produto como alternativa. A estimativa de compras depende de saídas e perdas registradas no histórico. Bancos existentes não são classificados automaticamente como reais ou demonstrativos; revise-os antes de qualquer limpeza.

O arquivo SQLite de demonstração e a pasta local `backups/` são ignorados pelo Git. Não os envie ao repositório: backups podem conter dados operacionais e são destinados à recuperação local.
