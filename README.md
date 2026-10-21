# Café Aroma do Sul | Gestão

ERP modular de homologação para cafeteria e restaurante, feito com Python, Streamlit, SQLAlchemy e SQLite.

## Executar

Requer Python 3.10 ou superior.

```powershell
py -3 -m pip install -r requirements.txt
py -3 -m streamlit run app.py
```

O banco configurado em `DATABASE_URL` é criado na primeira execução; o aplicativo não insere dados fictícios nesse banco automaticamente. Use `DATABASE_URL` para apontar para PostgreSQL ou outro banco suportado pelo SQLAlchemy.

## Homologação e produção

`MODO_HOMOLOGACAO = True` mantém o login desativado, permissões ignoradas e registra operações com `SISTEMA_HOMOLOGACAO`. Para ativar o login, defina `MODO_HOMOLOGACAO=False` em `config.py` ou use a variável de ambiente `MODO_HOMOLOGACAO=false`. Na primeira abertura será solicitado o cadastro do administrador. Perfis e permissões são inicializados no banco; o módulo administrativo de usuários permanece oculto até `MODULO_USUARIOS=True`.

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

O tema compartilhado define cores escuras de alto contraste para valores, rótulos, botões, campos e mensagens, incluindo os indicadores da página inicial e da visão geral. O tema e a marca visual do Café Aroma do Sul são configurados em `.streamlit/config.toml` e `components/layout.py`.

## Estrutura

- `models/`: entidades e tabelas SQLAlchemy.
- `database/`: conexão, sessões e criação do schema.
- `services/`: autenticação, regras operacionais e dados demonstrativos.
- `pages/`: módulos Streamlit.
- `components/`: layout e QR code de pedidos.
- `utils/`: formatação e utilitários.
- `tests/`: testes dos fluxos operacionais e da central de homologação.

Para abrir pedidos em um celular, inicie o Streamlit em um endereço de rede acessível e informe a URL no expansor de QR code do módulo Pedidos.

## Observações da versão

Esta entrega é uma base funcional para homologação, não substitui configuração operacional ou validação fiscal. Descontos e impostos da DRE ainda aparecem zerados até parametrização; a projeção usa saldo do caixa e contas a pagar/receber cadastradas, sem incorporar vendas automaticamente. CMV, DRE e margem de produto usam o custo calculado pela ficha técnica quando ela existe e o custo cadastrado do produto como alternativa. A estimativa de compras depende de saídas e perdas registradas no histórico. Bancos existentes não são classificados automaticamente como reais ou demonstrativos; revise-os antes de qualquer limpeza.

O arquivo SQLite de demonstração e a pasta local `backups/` são ignorados pelo Git. Não os envie ao repositório: backups podem conter dados operacionais e são destinados à recuperação local.
