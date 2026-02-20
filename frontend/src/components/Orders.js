import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  Form,
  Input,
  message,
  Modal,
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
const { TextArea } = Input;

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

export default function Orders() {
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

  const refreshChat = useCallback(async () => {
    if (!selectedOrder) return;
    try {
      const { data } = await axios.get(`/api/orders/${selectedOrder.id}/messages`);
      setChatMessages(data?.messages || []);
    } catch {
      // ignore
    }
  }, [selectedOrder]);

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
        fetchStats();
      } catch (err) {
        message.error(err?.response?.data?.detail || 'Не удалось обновить статус');
      }
    },
    [fetchOrders, fetchStats]
  );

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
      { title: 'Тип заявки', dataIndex: 'branch', width: 140 },
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
      <Card
        title={
          <Space>
            <ShoppingCartOutlined />
            Заявки
          </Space>
        }
        extra={
          <Space>
            <Select
              allowClear
              placeholder="Фильтр по статусу"
              style={{ width: 220 }}
              value={statusFilter}
              onChange={setStatusFilter}
            >
              {statusOptions.map((s) => (
                <Option key={s.value} value={s.value}>
                  {s.label}
                </Option>
              ))}
            </Select>
            <Button icon={<SyncOutlined />} onClick={reloadAll} loading={loading}>
              Обновить
            </Button>
          </Space>
        }
      >
        <Space style={{ marginBottom: 12 }}>
          <Statistic title="Всего" value={stats.total_orders} />
          <Statistic title="Новых" value={stats.new_orders} />
          <Statistic title="Активных" value={stats.active_orders} />
        </Space>

        <Table rowKey="id" loading={loading} columns={columns} dataSource={orders} pagination={{ pageSize: 20 }} />
      </Card>

      <Modal
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        footer={null}
        width={900}
        title={selectedOrder ? `Заявка #${selectedOrder.id}` : 'Заявка'}
      >
        {selectedOrder ? (
          <>
            <Space style={{ marginBottom: 12 }}>
              <Tag color={statusColor[selectedOrder.status] || 'default'}>
                {statusOptions.find((s) => s.value === selectedOrder.status)?.label || selectedOrder.status}
              </Tag>
              <Text type="secondary">{selectedOrder.branch}</Text>
              <Text type="secondary">
                {selectedOrder.created_at ? dayjs(selectedOrder.created_at).format('DD.MM.YYYY HH:mm') : ''}
              </Text>
            </Space>

            <Card size="small" title="Сообщения" style={{ marginBottom: 12 }}>
              <div style={{ maxHeight: 240, overflow: 'auto' }}>
                {chatMessages.length ? (
                  chatMessages.map((m) => (
                    <div key={m.id || `${m.created_at}-${m.direction}`} style={{ marginBottom: 8 }}>
                      <Badge status={m.direction === 'out' ? 'processing' : 'default'} />
                      <Text strong style={{ marginLeft: 6 }}>
                        {m.direction === 'out' ? 'Менеджер' : 'Клиент'}:
                      </Text>
                      <div style={{ marginLeft: 18 }}>{m.message_text}</div>
                      {m.created_at ? (
                        <Text type="secondary" style={{ marginLeft: 18, fontSize: 12 }}>
                          {dayjs(m.created_at).format('DD.MM.YYYY HH:mm')}
                        </Text>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <Text type="secondary">Пока нет сообщений</Text>
                )}
              </div>

              <Form form={msgForm} layout="vertical" onFinish={sendManagerMessage} style={{ marginTop: 12 }}>
                <Form.Item name="text" label="Ответить клиенту" rules={[{ required: true, message: 'Введите текст' }]}>
                  <TextArea rows={3} />
                </Form.Item>
                <Button type="primary" htmlType="submit" loading={sending}>
                  Отправить
                </Button>
                <Button style={{ marginLeft: 8 }} onClick={refreshChat} disabled={!selectedOrder}>
                  Обновить чат
                </Button>
              </Form>
            </Card>

            <Card size="small" title="Файлы">
              {files.length ? (
                files.map((f) => (
                  <div key={f.id || f.telegram_file_id} style={{ marginBottom: 8 }}>
                    <Tag>{f.original_name || 'Файл'}</Tag>
                    {f.file_url ? (
                      <a href={f.file_url} target="_blank" rel="noreferrer">
                        открыть
                      </a>
                    ) : (
                      <Text type="secondary"> (ссылка недоступна)</Text>
                    )}
                  </div>
                ))
              ) : (
                <Text type="secondary">Файлов нет</Text>
              )}
            </Card>
          </>
        ) : null}
      </Modal>
    </div>
  );
}
