import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Col,
  Form,
  Input,
  message,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import { ShoppingCartOutlined, SyncOutlined } from '@ant-design/icons';
import axios from 'axios';
import dayjs from 'dayjs';

const { Option } = Select;
const { Text } = Typography;

const statusOptions = [
  { value: 'draft', label: 'Черновик' },
  { value: 'new', label: 'Новая заявка' },
  { value: 'submitted', label: 'Новая заявка' },
  { value: 'in_work', label: 'В работе' },
  { value: 'done', label: 'Готово' },
  { value: 'canceled', label: 'Отменено' },
];

const statusColor = {
  draft: 'default',
  new: 'blue',
  submitted: 'blue',
  in_work: 'orange',
  done: 'green',
  canceled: 'red',
};

const Orders = () => {
  const [orders, setOrders] = useState([]);
  const [stats, setStats] = useState({ total_orders: 0, new_orders: 0, active_orders: 0 });
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState();
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [files, setFiles] = useState([]);
  const [chatMessages, setChatMessages] = useState([]);
  const [sending, setSending] = useState(false);
  const [msgForm] = Form.useForm();

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axios.get('/api/orders/', { params: { status_filter: statusFilter } });
      setOrders(Array.isArray(data) ? data : []);
    } catch {
      message.error('Не удалось загрузить заявки');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const { data } = await axios.get('/api/orders/stats');
      setStats(data || { total_orders: 0, new_orders: 0, active_orders: 0 });
    } catch {
      setStats({ total_orders: 0, new_orders: 0, active_orders: 0 });
    }
  }, []);

  const reloadAll = useCallback(async () => {
    await Promise.all([fetchOrders(), fetchStats()]);
  }, [fetchOrders, fetchStats]);

  useEffect(() => {
    reloadAll();
  }, [reloadAll]);

  const openOrder = useCallback(
    async (order) => {
      setSelectedOrder(order);
      setModalVisible(true);
      msgForm.resetFields();
      try {
        const [filesResp, msgResp] = await Promise.all([
          axios.get(`/api/orders/${order.id}/files`),
          axios.get(`/api/orders/${order.id}/messages`),
        ]);
        setFiles(filesResp.data?.files || []);
        setChatMessages(msgResp.data?.messages || []);
      } catch {
        setFiles([]);
        setChatMessages([]);
        message.warning('Не удалось загрузить файлы или чат по заявке');
      }
    },
    [msgForm]
  );

  const updateStatus = useCallback(
    async (id, status) => {
      try {
        await axios.put(`/api/orders/${id}`, { status });
        message.success('Статус обновлён');
        fetchOrders();
      } catch (err) {
        message.error(err?.response?.data?.detail || 'Не удалось обновить статус');
      }
    },
    [fetchOrders]
  );

  const refreshChat = useCallback(async () => {
    if (!selectedOrder) return;
    try {
      const { data } = await axios.get(`/api/orders/${selectedOrder.id}/messages`);
      setChatMessages(data?.messages || []);
    } catch {
      // ignore
    }
  }, [selectedOrder]);

  const sendManagerMessage = useCallback(
    async (values) => {
      if (!selectedOrder) return;
      const text = (values.text || '').trim();
      if (!text) return;

      setSending(true);
      try {
        await axios.post(`/api/orders/${selectedOrder.id}/messages`, { text });
        message.success('Сообщение отправлено в Telegram');
        msgForm.resetFields();
        await refreshChat();
      } catch (err) {
        message.error(err?.response?.data?.detail || 'Не удалось отправить сообщение в Telegram');
      } finally {
        setSending(false);
      }
    },
    [msgForm, refreshChat, selectedOrder]
  );

  const columns = useMemo(
    () => [
      { title: 'ID', dataIndex: 'id', width: 80 },
      {
        title: 'Клиент',
        render: (_, r) => (
          <div>
            <div>{r.full_name || 'Без имени'}</div>
            <Text type="secondary">@{r.username || '-'}</Text>
          </div>
        ),
      },
      { title: 'Тип заявки', dataIndex: 'branch', width: 160 },
      { title: 'Кратко', dataIndex: 'summary' },
      {
        title: 'Статус',
        width: 180,
        render: (_, r) => (
          <Select value={r.status} style={{ width: 170 }} onChange={(v) => updateStatus(r.id, v)}>
            {statusOptions.map((s) => (
              <Option key={s.value} value={s.value}>
                {s.label}
              </Option>
            ))}
          </Select>
        ),
      },
      {
        title: 'Дата',
        dataIndex: 'created_at',
        width: 170,
        render: (v) => (v ? dayjs(v).format('DD.MM.YYYY HH:mm') : '-'),
      },
      { title: 'Открыть', width: 110, render: (_, r) => <Button onClick={() => openOrder(r)}>Карточка</Button> },
    ],
    [openOrder, updateStatus]
  );

  return (
    <div>
      <h1>Заявки Chel3D</h1>

      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic title="Всего заявок" value={stats.total_orders} prefix={<ShoppingCartOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="Новые" value={stats.new_orders} prefix={<Badge dot status="processing" />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title="Активные" value={stats.active_orders} prefix={<SyncOutlined spin />} />
          </Card>
        </Col>
      </Row>

      <Space style={{ marginBottom: 12 }}>
        <span>Фильтр по статусу:</span>
        <Select
          allowClear
          placeholder="Все"
          style={{ width: 220 }}
          value={statusFilter}
          onChange={(v) => setStatusFilter(v)}
        >
          {statusOptions.map((s) => (
            <Option key={s.value} value={s.value}>
              {s.label}
            </Option>
          ))}
        </Select>
        <Button onClick={reloadAll} loading={loading}>
          Обновить
        </Button>
      </Space>

      <Table rowKey="id" loading={loading} columns={columns} dataSource={orders} pagination={{ pageSize: 20 }} />

      <Modal
        open={modalVisible}
        title={selectedOrder ? `Заявка #${selectedOrder.id}` : 'Заявка'}
        onCancel={() => setModalVisible(false)}
        footer={null}
        width={900}
      >
        {selectedOrder && (
          <>
            <Space style={{ marginBottom: 12 }} wrap>
              <Tag color={statusColor[selectedOrder.status] || 'default'}>
                {selectedOrder.status_label || selectedOrder.status}
              </Tag>
              <Tag>Тип: {selectedOrder.branch}</Tag>
              <Tag>
                Клиент: {selectedOrder.full_name || '—'} (@{selectedOrder.username || '—'})
              </Tag>
              <Tag>
                Создано:{' '}
                {selectedOrder.created_at ? dayjs(selectedOrder.created_at).format('DD.MM.YYYY HH:mm') : '—'}
              </Tag>
            </Space>

            <Card size="small" title="Файлы" style={{ marginBottom: 12 }}>
              {files.length === 0 ? (
                <Text type="secondary">Файлов нет</Text>
              ) : (
                <Space direction="vertical" style={{ width: '100%' }}>
                  {files.map((f) => (
                    <Card key={f.id} size="small">
                      <Space direction="vertical" style={{ width: '100%' }}>
                        <div>
                          <b>{f.original_name || 'Файл'}</b>{' '}
                          <Text type="secondary">{f.file_size ? `${Math.round(f.file_size / 1024)} KB` : ''}</Text>
                        </div>
                        {f.file_url ? (
                          <a href={f.file_url} target="_blank" rel="noreferrer">
                            Скачать / открыть
                          </a>
                        ) : (
                          <Text type="secondary">Ссылка временно недоступна</Text>
                        )}
                      </Space>
                    </Card>
                  ))}
                </Space>
              )}
            </Card>

            <Card
              size="small"
              title="Чат с клиентом"
              extra={
                <Button onClick={refreshChat} disabled={!selectedOrder}>
                  Обновить чат
                </Button>
              }
              style={{ marginBottom: 12 }}
            >
              <Space direction="vertical" style={{ width: '100%' }}>
                {chatMessages.length === 0 ? (
                  <Text type="secondary">Сообщений пока нет</Text>
                ) : (
                  chatMessages.map((m) => (
                    <Card key={m.id} size="small">
                      <Space direction="vertical" style={{ width: '100%' }}>
                        <div>
                          <Tag color={m.direction === 'out' ? 'green' : 'blue'}>
                            {m.direction === 'out' ? 'Менеджер → клиент' : 'Клиент → менеджер'}
                          </Tag>
                          <Text type="secondary">
                            {m.created_at ? dayjs(m.created_at).format('DD.MM.YYYY HH:mm') : ''}
                          </Text>
                        </div>
                        <div style={{ whiteSpace: 'pre-wrap' }}>{m.message_text}</div>
                      </Space>
                    </Card>
                  ))
                )}
              </Space>
            </Card>

            <Card size="small" title="Ответить клиенту">
              <Form form={msgForm} layout="vertical" onFinish={sendManagerMessage}>
                <Form.Item name="text" label="Текст" rules={[{ required: true, message: 'Введите текст сообщения' }]}>
                  <Input.TextArea rows={4} placeholder="Напишите сообщение клиенту..." />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={sending} disabled={!selectedOrder}>
                  Отправить в Telegram
                </Button>
              </Form>
            </Card>
          </>
        )}
      </Modal>
    </div>
  );
};

export default Orders;
